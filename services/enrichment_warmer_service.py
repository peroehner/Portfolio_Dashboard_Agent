"""Background paced enrichment warmer (fundamentals + news).

Mirrors the price-sync pattern: a daemon thread walks the union of all users'
symbols in priority order, warming a small chunk each cycle with pauses so
Finnhub/Yahoo bursts do not stall user-facing requests.

Priority (when available on the backend):
  1. Starred symbols (``symbols.is_starred``)
  2. Held symbols (positive quantity in ``holdings``)
  3. Remaining watchlist symbols
"""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING

from db.database import list_distinct_symbols, list_held_symbols, list_starred_symbols

if TYPE_CHECKING:
    from services.fundamentals_service import FundamentalsService

logger = logging.getLogger(__name__)


def warmer_enabled() -> bool:
    return os.environ.get("ENRICHMENT_WARMER", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def warm_interval_seconds() -> int:
    return max(60, int(os.environ.get("ENRICHMENT_WARM_INTERVAL_SECONDS", "300")))


def warm_chunk_size() -> int:
    return max(1, int(os.environ.get("ENRICHMENT_WARM_CHUNK_SIZE", "4")))


def warm_pause_seconds() -> float:
    return max(0.0, float(os.environ.get("ENRICHMENT_WARM_PAUSE_SECONDS", "1.5")))


def build_warm_priority_queue() -> list[str]:
    """Order symbols: starred → held → rest (stable alphabetical within tiers)."""
    all_symbols = list_distinct_symbols()
    if not all_symbols:
        return []
    starred = set(list_starred_symbols())
    held = set(list_held_symbols())
    ordered: list[str] = []
    seen: set[str] = set()
    for tier in (starred, held, set(all_symbols)):
        for symbol in all_symbols:
            if symbol in tier and symbol not in seen:
                ordered.append(symbol)
                seen.add(symbol)
    return ordered


def run_warm_cycle(fundamentals_service: FundamentalsService) -> dict[str, int]:
    """Warm up to ``warm_chunk_size()`` stale symbols, starred first."""
    if not fundamentals_service.enabled:
        return {"queued": 0, "warmed": 0, "skipped": 0}

    queue = build_warm_priority_queue()
    if not queue:
        return {"queued": 0, "warmed": 0, "skipped": 0}

    chunk_limit = warm_chunk_size()
    pause = warm_pause_seconds()
    warmed = 0
    skipped = 0

    for symbol in queue:
        if warmed >= chunk_limit:
            break
        if not fundamentals_service.symbol_needs_warm(symbol):
            skipped += 1
            continue
        try:
            fundamentals_service.warm_symbol(symbol)
            warmed += 1
            logger.info("Enrichment warmer: warmed %s (%s/%s)", symbol, warmed, chunk_limit)
        except Exception:  # noqa: BLE001 - one symbol must not block the queue
            logger.exception("Enrichment warmer failed for %s", symbol)
        if warmed < chunk_limit and pause > 0:
            time.sleep(pause)

    if warmed:
        logger.info(
            "Enrichment warm cycle complete: warmed=%s skipped_fresh=%s queue=%s",
            warmed,
            skipped,
            len(queue),
        )
    return {"queued": len(queue), "warmed": warmed, "skipped": skipped}
