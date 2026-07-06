"""Background daily pre-warm of shared base assessments (symbol_assessment).

Runs once per UTC day after a successful price sync, computing (or reusing)
one base LLM assessment per distinct ticker. Per-user overlay assessments
remain API-triggered.
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from db.database import get_connection, list_distinct_symbols
from services.symbol_assessment_service import SymbolAssessmentService, utc_today_iso

logger = logging.getLogger(__name__)

_META_KEY = "daily_assessment_last_date"


def daily_assessment_enabled() -> bool:
    return os.environ.get("DAILY_ASSESSMENT_WORKER", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _last_run_date() -> str | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT value FROM app_meta WHERE key = %s",
            (_META_KEY,),
        ).fetchone()
    return str(row["value"]) if row else None


def _mark_run_complete(as_of_date: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO app_meta (key, value)
            VALUES (%s, %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """,
            (_META_KEY, as_of_date),
        )
        conn.commit()


def should_run_today() -> bool:
    if not daily_assessment_enabled():
        return False
    return _last_run_date() != utc_today_iso()


def run_daily_assessments(symbols: list[str] | None = None) -> dict[str, Any]:
    """Pre-warm today's base assessments for the given symbols (or all distinct tickers)."""
    if not daily_assessment_enabled():
        return {"skipped": True, "reason": "disabled"}

    today = utc_today_iso()
    if _last_run_date() == today:
        return {"skipped": True, "reason": "already_ran", "date": today}

    tickers = [s.upper() for s in (symbols or list_distinct_symbols())]
    if not tickers:
        return {"skipped": True, "reason": "no_symbols", "date": today}

    workers = max(1, int(os.environ.get("ASSESS_WORKERS", "6")))
    service = SymbolAssessmentService()
    computed = 0
    cached = 0
    errors: list[dict[str, str]] = []

    def _assess_one(symbol: str) -> tuple[str, bool | None, str | None]:
        try:
            result = service.get_or_compute_today(symbol)
            return symbol, bool(result.get("fromCache")), None
        except Exception as exc:  # noqa: BLE001 - continue other symbols
            return symbol, None, str(exc)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_assess_one, symbol) for symbol in tickers]
        for future in as_completed(futures):
            symbol, from_cache, error = future.result()
            if error:
                errors.append({"symbol": symbol, "error": error})
                logger.warning("Daily assessment failed for %s: %s", symbol, error)
            elif from_cache:
                cached += 1
            else:
                computed += 1

    _mark_run_complete(today)
    summary = {
        "date": today,
        "symbols": len(tickers),
        "computed": computed,
        "cached": cached,
        "errors": errors,
    }
    logger.info(
        "Daily assessment worker: %s computed, %s cached, %s errors (UTC %s).",
        computed,
        cached,
        len(errors),
        today,
    )
    return summary
