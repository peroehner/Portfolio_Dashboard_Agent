"""In-process status for background workers (price sync + enrichment warmer).

Written by daemon threads in ``main.py``; read by the author Consol snapshot.
Not shared across Gunicorn workers — each process reports its own last cycle.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

_lock = threading.Lock()
_price_sync: dict[str, Any] = {}
_enrichment_warm: dict[str, Any] = {}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def record_price_sync(
    *,
    symbol_count: int,
    updated: int,
    new_alerts: int,
    refresh_targets: bool,
    error: str | None = None,
) -> None:
    with _lock:
        _price_sync.clear()
        _price_sync.update(
            {
                "at": _utc_now_iso(),
                "source": "yahoo",
                "destination": "postgres:symbol_market",
                "symbolCount": int(symbol_count),
                "updated": int(updated),
                "newAlerts": int(new_alerts),
                "refreshTargets": bool(refresh_targets),
                "error": error,
            }
        )


def record_enrichment_warm(
    *,
    queued: int,
    warmed: int,
    skipped: int,
    enabled: bool = True,
    error: str | None = None,
) -> None:
    with _lock:
        _enrichment_warm.clear()
        _enrichment_warm.update(
            {
                "at": _utc_now_iso(),
                "source": "yahoo/finnhub",
                "destination": "postgres:symbol_market (fundamentals_json, news_json)",
                "enabled": bool(enabled),
                "queued": int(queued),
                "warmed": int(warmed),
                "skippedFresh": int(skipped),
                "error": error,
            }
        )


def record_enrichment_warm_disabled() -> None:
    with _lock:
        _enrichment_warm.clear()
        _enrichment_warm.update(
            {
                "at": _utc_now_iso(),
                "enabled": False,
                "queued": 0,
                "warmed": 0,
                "skippedFresh": 0,
                "error": None,
            }
        )


def worker_status_snapshot() -> dict[str, Any]:
    with _lock:
        return {
            "priceSync": dict(_price_sync) if _price_sync else None,
            "enrichmentWarm": dict(_enrichment_warm) if _enrichment_warm else None,
        }
