"""Author console snapshots: workload counts, DB payload sizes, process memory."""

from __future__ import annotations

import platform
import resource
from typing import Any

from db.database import get_connection


def _read_linux_rss_kb() -> float | None:
    try:
        with open("/proc/self/status", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    return float(line.split()[1])
    except OSError:
        return None
    return None


def process_memory() -> dict[str, float | None]:
    """Best-effort RSS for the current worker process (MB)."""
    rss_kb: float | None = None
    if platform.system() == "Linux":
        rss_kb = _read_linux_rss_kb()
    if rss_kb is None:
        usage = resource.getrusage(resource.RUSAGE_SELF)
        raw = float(usage.ru_maxrss or 0)
        if platform.system() == "Darwin":
            rss_kb = raw / 1024.0
        else:
            rss_kb = raw
    rss_mb = round(rss_kb / 1024.0, 1) if rss_kb else None
    return {"rssMb": rss_mb}


def _footprint_rows(conn) -> list[dict[str, Any]]:
    """Row counts and stored payload bytes per logical data category."""
    queries: tuple[tuple[str, str, str], ...] = (
      (
          "notes",
          "Notes",
          """
          SELECT
              COUNT(*)::bigint AS row_count,
              COALESCE(SUM(
                  octet_length(COALESCE(text, ''))
                  + octet_length(COALESCE(synthesis, ''))
                  + octet_length(COALESCE(note_date, ''))
                  + octet_length(COALESCE(source, ''))
              ), 0)::bigint AS payload_bytes
          FROM notes
          """,
      ),
      (
          "agent_reads",
          "Agent Reads",
          """
          SELECT
              COUNT(*)::bigint AS row_count,
              COALESCE(SUM(
                  octet_length(COALESCE(rationale, ''))
                  + octet_length(COALESCE(factors, ''))
                  + octet_length(COALESCE(note_synthesis, ''))
                  + octet_length(COALESCE(trading_recommendation, ''))
              ), 0)::bigint AS payload_bytes
          FROM assessments
          """,
      ),
      (
          "shared_sai",
          "Shared SAI (base)",
          """
          SELECT
              COUNT(*)::bigint AS row_count,
              COALESCE(SUM(
                  octet_length(COALESCE(rationale, ''))
                  + octet_length(COALESCE(factors, ''))
                  + octet_length(COALESCE(trading_recommendation, ''))
                  + COALESCE(pg_column_size(analysis_json), 0)
              ), 0)::bigint AS payload_bytes
          FROM symbol_assessment
          """,
      ),
      (
          "sai_changes",
          "SAI Changes",
          """
          SELECT
              COUNT(*)::bigint AS row_count,
              COALESCE(SUM(
                  octet_length(COALESCE(old_action, ''))
                  + octet_length(COALESCE(new_action, ''))
                  + octet_length(COALESCE(old_confidence, ''))
                  + octet_length(COALESCE(new_confidence, ''))
                  + octet_length(COALESCE(provider, ''))
              ), 0)::bigint AS payload_bytes
          FROM recommendation_changelog
          """,
      ),
      (
          "symbols_thresholds",
          "Symbols & thresholds",
          """
          SELECT COUNT(*)::bigint AS row_count,
                 COALESCE(SUM(
                     octet_length(symbol)
                     + COALESCE(pg_column_size(target_price), 0)
                     + COALESCE(pg_column_size(buy_below), 0)
                     + COALESCE(pg_column_size(sell_above), 0)
                     + COALESCE(pg_column_size(trade_below_price), 0)
                     + COALESCE(pg_column_size(trade_above_price), 0)
                     + COALESCE(pg_column_size(trade_below_shares), 0)
                     + COALESCE(pg_column_size(trade_above_shares), 0)
                 ), 0)::bigint AS payload_bytes
          FROM symbols
          """,
      ),
      (
          "holdings",
          "Holdings",
          """
          SELECT COUNT(*)::bigint AS row_count,
                 COALESCE(SUM(
                     COALESCE(pg_column_size(quantity), 0)
                     + COALESCE(pg_column_size(cost_basis), 0)
                     + octet_length(COALESCE(purchase_date, ''))
                     + octet_length(COALESCE(account_name, ''))
                 ), 0)::bigint AS payload_bytes
          FROM holdings
          """,
      ),
      (
          "alerts",
          "Alerts",
          """
          SELECT
              COUNT(*)::bigint AS row_count,
              COALESCE(SUM(
                  octet_length(COALESCE(message, ''))
                  + octet_length(COALESCE(symbol, ''))
                  + octet_length(COALESCE(fib_level, ''))
              ), 0)::bigint AS payload_bytes
          FROM alerts
          """,
      ),
      (
          "signal_outcomes",
          "Agent Signal Record",
          """
          SELECT COUNT(*)::bigint AS row_count,
                 COALESCE(SUM(
                     octet_length(COALESCE(label, ''))
                     + octet_length(COALESCE(kind, ''))
                     + COALESCE(pg_column_size(entry_price), 0)
                     + COALESCE(pg_column_size(eval_price), 0)
                 ), 0)::bigint AS payload_bytes
          FROM signal_outcomes
          """,
      ),
      (
          "symbol_market",
          "Shared market data",
          """
          SELECT
              COUNT(*)::bigint AS row_count,
              COALESCE(SUM(
                  COALESCE(pg_column_size(current_price), 0)
                  + COALESCE(pg_column_size(analyst_target_1y), 0)
                  + octet_length(COALESCE(company_name, ''))
                  + COALESCE(pg_column_size(fundamentals_json), 0)
              ), 0)::bigint AS payload_bytes
          FROM symbol_market
          """,
      ),
      (
          "symbol_technical",
          "Imported TA snapshots",
          """
          SELECT
              COUNT(*)::bigint AS row_count,
              COALESCE(SUM(
                  octet_length(COALESCE(trends_json, ''))
                  + octet_length(COALESCE(fib_levels_json, ''))
              ), 0)::bigint AS payload_bytes
          FROM symbol_technical
          """,
      ),
      (
          "simulation",
          "Simulation snapshots",
          """
          SELECT
              COUNT(*)::bigint AS row_count,
              COALESCE(SUM(COALESCE(pg_column_size(payload), 0)), 0)::bigint AS payload_bytes
          FROM simulation_snapshots
          """,
      ),
  )

    rows: list[dict[str, Any]] = []
    for key, label, sql in queries:
        row = conn.execute(sql).fetchone()
        rows.append(
            {
                "key": key,
                "label": label,
                "rowCount": int(row["row_count"] or 0),
                "payloadBytes": int(row["payload_bytes"] or 0),
                "storage": "database",
            }
        )
    return rows


def _in_process_caches() -> list[dict[str, Any]]:
    from services.fib_service import fib_levels_cache_footprint
    from services.fundamentals_service import (
        analyst_targets_cache,
        finnhub_fundamentals_cache,
        news_cache,
        yf_failure_cache,
    )
    from services.market_cache import ticker_info_cache
    from services.news_relevance_service import _INTRADAY_CACHE, _PRICE_CACHE
    from services.overview_service import _YTD_PRICE_CACHE
    from services.technical_signals_service import _history_cache, _history_fail_cache

    named: list[tuple[str, Any]] = [
        ("ticker_info", ticker_info_cache),
        ("technical_history", _history_cache),
        ("technical_history_fail", _history_fail_cache),
        ("news", news_cache),
        ("finnhub_fundamentals", finnhub_fundamentals_cache),
        ("analyst_targets", analyst_targets_cache),
        ("yf_failure", yf_failure_cache),
        ("news_relevance_prices", _PRICE_CACHE),
        ("news_relevance_intraday", _INTRADAY_CACHE),
        ("ytd_prices", _YTD_PRICE_CACHE),
    ]
    caches: list[dict[str, Any]] = []
    for name, cache in named:
        fp = cache.footprint()
        caches.append(
            {
                "key": name,
                "label": name.replace("_", " "),
                "rowCount": fp["entries"],
                "payloadBytes": fp["approxBytes"],
                "maxEntries": fp["maxEntries"],
                "storage": "memory",
            }
        )
    caches.append({**fib_levels_cache_footprint(), "storage": "memory"})
    return caches


def build_footprint_snapshot() -> dict[str, Any]:
    with get_connection() as conn:
        db_rows = _footprint_rows(conn)
    cache_rows = _in_process_caches()
    db_bytes = sum(row["payloadBytes"] for row in db_rows)
    cache_bytes = sum(row["payloadBytes"] for row in cache_rows)
    return {
        "process": process_memory(),
        "database": {
            "totalPayloadBytes": db_bytes,
            "categories": db_rows,
        },
        "caches": {
            "totalApproxBytes": cache_bytes,
            "categories": cache_rows,
        },
    }
