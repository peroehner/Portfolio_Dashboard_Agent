"""Small in-process TTL caches for yfinance payloads (keeps Render memory stable)."""
from __future__ import annotations

import contextlib
import os
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Hashable, TypeVar

T = TypeVar("T")

# Sentinel returned by TtlCache.peek when a key is absent/expired.
CACHE_MISS = object()


class TtlCache:
    def __init__(self, ttl_seconds: float, max_entries: int = 64):
        self.ttl = float(ttl_seconds)
        self.max_entries = max(1, int(max_entries))
        self._entries: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: Hashable, factory: Callable[[], T]) -> T:
        now = time.time()
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                expires_at, value = entry
                if expires_at > now:
                    self._entries.move_to_end(key)
                    return value
                del self._entries[key]

        value = factory()
        with self._lock:
            self._entries[key] = (now + self.ttl, value)
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
        return value

    def peek(self, key: Hashable) -> Any:
        """Return the cached value if present and fresh, else CACHE_MISS."""
        now = time.time()
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                expires_at, value = entry
                if expires_at > now:
                    self._entries.move_to_end(key)
                    return value
                del self._entries[key]
        return CACHE_MISS

    def put(self, key: Hashable, value: Any) -> None:
        now = time.time()
        with self._lock:
            self._entries[key] = (now + self.ttl, value)
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def footprint(self) -> dict[str, int | float]:
        """Approximate in-process footprint for author console diagnostics."""
        approx_bytes = 0
        with self._lock:
            count = len(self._entries)
            for _key, (_expires_at, value) in self._entries.items():
                approx_bytes += _approx_payload_bytes(value)
        return {
            "entries": count,
            "maxEntries": self.max_entries,
            "ttlSeconds": self.ttl,
            "approxBytes": approx_bytes,
        }

    def entry_breakdown(self, limit: int = 15) -> list[dict[str, Any]]:
        """Per-key payload sizes, largest first (skips expired entries)."""
        now = time.time()
        items: list[tuple[str, int]] = []
        with self._lock:
            for key, (expires_at, value) in self._entries.items():
                if expires_at <= now:
                    continue
                items.append((_cache_key_label(key), _approx_payload_bytes(value)))
        items.sort(key=lambda pair: pair[1], reverse=True)
        cap = max(1, int(limit))
        return [
            {"label": label, "payloadBytes": nbytes}
            for label, nbytes in items[:cap]
        ]


def _cache_key_label(key: Hashable) -> str:
    if isinstance(key, tuple):
        return "/".join(str(part) for part in key)
    return str(key)


def _approx_payload_bytes(value: Any) -> int:
    import json

    if value is None:
        return 0
    try:
        import pandas as pd

        if isinstance(value, pd.DataFrame):
            return int(value.memory_usage(deep=True).sum())
        if isinstance(value, pd.Series):
            return int(value.memory_usage(deep=True))
    except Exception:  # noqa: BLE001
        pass
    try:
        return len(json.dumps(value, default=str).encode("utf-8"))
    except Exception:  # noqa: BLE001
        return 64


_ticker_info_ttl = float(os.environ.get("YFINANCE_INFO_CACHE_TTL_SECONDS", "900"))
_ticker_info_max = int(os.environ.get("YFINANCE_INFO_CACHE_MAX_ENTRIES", "48"))
ticker_info_cache: TtlCache = TtlCache(_ticker_info_ttl, _ticker_info_max)


# --- Per-thread yfinance session ---------------------------------------------
# Yahoo's quoteSummary endpoint (yf.Ticker.info) is frequently blocked/rate
# limited from datacenter IPs (e.g. Render), returning empty info while the
# lightweight price/news endpoints still work. A browser-impersonating
# curl_cffi session gets a valid cookie+crumb far more reliably.
#
# IMPORTANT: curl_cffi sessions are NOT thread-safe, and fundamentals are
# fetched concurrently via a ThreadPoolExecutor. Sharing one session across
# threads crashes the worker (502). We therefore keep one session PER THREAD
# via thread-local storage. If curl_cffi is unavailable we fall back to the
# default yfinance session (no behavior change).
_yf_local = threading.local()
_yf_impersonate = os.environ.get("YF_IMPERSONATE", "chrome").strip()
_yf_disabled = _yf_impersonate.lower() in ("", "0", "off", "none", "false")


def get_yf_session() -> Any:
    if _yf_disabled:
        return None
    if getattr(_yf_local, "ready", False):
        return _yf_local.session
    session: Any = None
    try:
        from curl_cffi import requests as cffi_requests

        session = cffi_requests.Session(impersonate=_yf_impersonate)
    except Exception:  # noqa: BLE001 - optional dependency / runtime issue
        session = None
    _yf_local.session = session
    _yf_local.ready = True
    return session


def reset_yf_session() -> None:
    """Drop this thread's cached yfinance session so the next call rebuilds it.

    Yahoo invalidates a session's cookie+crumb after a while (the "401 Invalid
    Crumb" error). Because each worker thread caches one curl_cffi session for
    its whole life, a single invalidation would otherwise leave that thread
    permanently fetching against a dead session until the process restarts.
    Calling this after a failed fetch lets the thread recover on its own.
    """
    session = getattr(_yf_local, "session", None)
    if session is not None:
        try:
            session.close()
        except Exception:  # noqa: BLE001 - best-effort cleanup
            pass
    _yf_local.session = None
    _yf_local.ready = False


# --- Process-wide yfinance throttle ------------------------------------------
# Every Yahoo network call (history / info / news / analyst targets / balance
# sheet, plus the bulk yf.download used by the engine and overview) funnels
# through this bounded semaphore. Without it, the background sync, the Patterns
# view, the fundamentals fetcher, and the Inspector each open their own
# ThreadPoolExecutor and collectively flood Yahoo, tripping its rate limiter —
# which silently blanks out pattern/trend data for a couple of minutes. Capping
# *total* concurrency keeps every subsystem polite to Yahoo regardless of which
# one is busy.
_yf_max_concurrency = max(1, int(os.environ.get("YFINANCE_MAX_CONCURRENCY", "4")))
_yf_min_interval = max(
    0.0, float(os.environ.get("YFINANCE_MIN_REQUEST_INTERVAL_SECONDS", "0"))
)
_yf_semaphore = threading.BoundedSemaphore(_yf_max_concurrency)
_yf_interval_lock = threading.Lock()
_yf_last_request = [0.0]


def _make_yf_pool():
    """A process-wide, persistent worker pool for parallel Yahoo fetches.

    Per-request ThreadPoolExecutors (the Patterns view, /patterns) used to spawn
    fresh threads on every call; each new thread made yfinance reopen its SQLite
    timezone/cookie caches and never closed them when the thread died, leaking
    file descriptors until the process hit its open-file limit and started
    silently returning empty history. Reusing a fixed set of worker threads keeps
    the number of yfinance cache handles bounded for the life of the process.
    """
    from concurrent.futures import ThreadPoolExecutor

    workers = max(1, int(os.environ.get("YFINANCE_POOL_WORKERS", str(_yf_max_concurrency + 2))))
    return ThreadPoolExecutor(max_workers=workers, thread_name_prefix="yf-pool")


yf_pool = _make_yf_pool()


@contextlib.contextmanager
def yf_throttle():
    """Bound total concurrent Yahoo requests across every subsystem."""
    with _yf_semaphore:
        if _yf_min_interval > 0:
            with _yf_interval_lock:
                wait = _yf_last_request[0] + _yf_min_interval - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                _yf_last_request[0] = time.monotonic()
        yield


# Ticker properties that hit the network when accessed, so they're throttled.
_THROTTLED_PROPS = frozenset(
    {
        "info",
        "fast_info",
        "news",
        "analyst_price_targets",
        "balance_sheet",
        "income_stmt",
        "cashflow",
        "earnings",
        "calendar",
        "quarterly_income_stmt",
        "quarterly_balance_sheet",
        "quarterly_cashflow",
    }
)


class _ThrottledTicker:
    """Wraps a yf.Ticker so its network-bound access passes through yf_throttle()."""

    __slots__ = ("_t",)

    def __init__(self, ticker: Any):
        object.__setattr__(self, "_t", ticker)

    def history(self, *args, **kwargs):
        with yf_throttle():
            return self._t.history(*args, **kwargs)

    def __getattr__(self, name: str):
        # `_t` is a slot, so it never routes here; only attribute lookups that
        # miss the class (i.e. the underlying ticker's members) reach this.
        if name in _THROTTLED_PROPS:
            with yf_throttle():
                return getattr(self._t, name)
        return getattr(self._t, name)


def make_ticker(symbol: str):
    """Return a throttled yf.Ticker, using the impersonating session when available."""
    import yfinance as yf

    session = get_yf_session()
    ticker = None
    if session is not None:
        try:
            ticker = yf.Ticker(symbol, session=session)
        except TypeError:
            # Older/newer yfinance without a session kwarg.
            ticker = None
    if ticker is None:
        ticker = yf.Ticker(symbol)
    return _ThrottledTicker(ticker)
