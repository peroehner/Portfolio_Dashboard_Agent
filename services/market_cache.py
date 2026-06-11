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
