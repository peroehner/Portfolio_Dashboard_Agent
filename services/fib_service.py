import os
import threading
import time
from collections import OrderedDict
from typing import Any

from services.market_cache import make_ticker

FIB_RATIOS = (0.236, 0.382, 0.5, 0.618, 0.786)

_LEVELS_CACHE: OrderedDict[tuple[str, str], tuple[float, dict[str, Any] | None]] = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_MAX_ENTRIES = int(os.environ.get("FIB_CACHE_MAX_ENTRIES", "64"))


class FibService:
    def __init__(self, period: str | None = None):
        self.period = period or os.environ.get("FIB_LOOKBACK_PERIOD", "90d")
        self.cache_ttl = float(os.environ.get("FIB_CACHE_TTL_SECONDS", "900"))

    def get_levels(self, symbol: str, *, use_cache: bool = True) -> dict[str, Any] | None:
        symbol = symbol.upper()
        cache_key = (symbol, self.period)
        if use_cache:
            cached = self._cache_get(cache_key)
            if cached is not None or self._cache_has_key(cache_key):
                return cached

        levels = self._fetch_levels(symbol)
        if use_cache:
            self._cache_set(cache_key, levels)
        return levels

    @classmethod
    def clear_cache(cls) -> None:
        with _CACHE_LOCK:
            _LEVELS_CACHE.clear()

    def closest_level(
        self,
        symbol: str,
        price: float,
        fib: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if price is None:
            return None
        if fib is None:
            fib = self.get_levels(symbol)
        if not fib:
            return None

        closest = None
        closest_distance = None
        for level in fib["levels"]:
            distance_pct = abs(price - level["price"]) / price * 100
            if closest_distance is None or distance_pct < closest_distance:
                closest = level
                closest_distance = distance_pct

        if closest is None:
            return None

        return {
            "fib": fib,
            "level": closest,
            "distancePct": round(closest_distance, 2),
        }

    def nearest_level(
        self,
        symbol: str,
        price: float,
        proximity_pct: float,
        fib: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        closest = self.closest_level(symbol, price, fib=fib)
        if closest is None or closest["distancePct"] > proximity_pct:
            return None
        return closest

    def _fetch_levels(self, symbol: str) -> dict[str, Any] | None:
        symbol = symbol.upper()
        data = None
        try:
            data = make_ticker(symbol).history(period=self.period, auto_adjust=True)
            if data.empty:
                return None

            swing_high = float(data["High"].max())
            swing_low = float(data["Low"].min())
            if swing_high <= swing_low:
                return None

            span = swing_high - swing_low
            levels = []
            for ratio in FIB_RATIOS:
                price = round(swing_high - span * ratio, 2)
                levels.append(
                    {
                        "label": f"{ratio * 100:.1f}%",
                        "ratio": ratio,
                        "price": price,
                    }
                )

            return {
                "symbol": symbol,
                "period": self.period,
                "swingHigh": round(swing_high, 2),
                "swingLow": round(swing_low, 2),
                "levels": levels,
            }
        except Exception:
            return None
        finally:
            data = None

    def _cache_get(self, cache_key: tuple[str, str]) -> dict[str, Any] | None:
        now = time.time()
        with _CACHE_LOCK:
            entry = _LEVELS_CACHE.get(cache_key)
            if entry is None:
                return None
            expires_at, payload = entry
            if expires_at <= now:
                del _LEVELS_CACHE[cache_key]
                return None
            _LEVELS_CACHE.move_to_end(cache_key)
            return payload

    def _cache_has_key(self, cache_key: tuple[str, str]) -> bool:
        now = time.time()
        with _CACHE_LOCK:
            entry = _LEVELS_CACHE.get(cache_key)
            if entry is None:
                return False
            expires_at, _payload = entry
            if expires_at <= now:
                del _LEVELS_CACHE[cache_key]
                return False
            _LEVELS_CACHE.move_to_end(cache_key)
            return True

    def _cache_set(self, cache_key: tuple[str, str], payload: dict[str, Any] | None) -> None:
        expires_at = time.time() + self.cache_ttl
        with _CACHE_LOCK:
            _LEVELS_CACHE[cache_key] = (expires_at, payload)
            _LEVELS_CACHE.move_to_end(cache_key)
            while len(_LEVELS_CACHE) > _CACHE_MAX_ENTRIES:
                _LEVELS_CACHE.popitem(last=False)


def fib_levels_cache_footprint() -> dict[str, Any]:
    import json

    approx_bytes = 0
    with _CACHE_LOCK:
        count = len(_LEVELS_CACHE)
        for _key, (_expires_at, payload) in _LEVELS_CACHE.items():
            if payload is None:
                continue
            try:
                approx_bytes += len(json.dumps(payload, default=str).encode("utf-8"))
            except Exception:  # noqa: BLE001
                approx_bytes += 64
    return {
        "key": "fib_levels",
        "label": "fib levels",
        "rowCount": count,
        "payloadBytes": approx_bytes,
        "maxEntries": _CACHE_MAX_ENTRIES,
    }
