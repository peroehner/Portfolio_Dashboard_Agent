"""Small in-process TTL caches for yfinance payloads (keeps Render memory stable)."""
from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Hashable, TypeVar

T = TypeVar("T")


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

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


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


def make_ticker(symbol: str):
    """Return a yf.Ticker, using the impersonating session when available."""
    import yfinance as yf

    session = get_yf_session()
    if session is not None:
        try:
            return yf.Ticker(symbol, session=session)
        except TypeError:
            # Older/newer yfinance without a session kwarg.
            pass
    return yf.Ticker(symbol)
