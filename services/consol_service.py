"""Author console snapshots: workload counts, DB payload sizes, process memory."""

from __future__ import annotations

import platform
import resource
import time
from datetime import datetime, timezone
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
                  + COALESCE(pg_column_size(news_json), 0)
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
        _52w_range_cache,
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
        ("fundamentals_52w_history", _52w_range_cache),
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
                "ttlSeconds": fp["ttlSeconds"],
                "storage": "memory",
            }
        )
    fib_fp = fib_levels_cache_footprint()
    caches.append({**fib_fp, "storage": "memory"})
    return caches


def _history_cache_breakdown() -> list[dict[str, Any]]:
    from services.technical_signals_service import _history_cache

    rows = _history_cache.entry_breakdown(limit=15)
    for row in rows:
        label = str(row.get("label") or "")
        symbol = label.split("/", 1)[0] if label else label
        row["symbol"] = symbol
    return rows


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
            "historyBySymbol": _history_cache_breakdown(),
        },
    }


def _parse_fetched_at(value: str | None) -> float | None:
    if not value:
        return None
    try:
        dt = datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


def _blob_age_summary(
    conn,
    column: str,
    *,
    ttl_seconds: float,
) -> dict[str, Any]:
    """Fresh vs stale counts for a symbol_market JSONB blob with fetchedAt."""
    if column not in ("fundamentals_json", "news_json"):
        raise ValueError(f"unsupported column: {column}")
    rows = conn.execute(
        f"""
        SELECT
            symbol,
            {column}->>'fetchedAt' AS fetched_at
        FROM symbol_market
        WHERE {column} IS NOT NULL
        """
    ).fetchall()
    now = time.time()
    oldest: str | None = None
    newest: str | None = None
    oldest_ts: float | None = None
    newest_ts: float | None = None
    fresh = 0
    stale = 0
    for row in rows:
        fetched_at = row.get("fetched_at")
        ts = _parse_fetched_at(fetched_at)
        if ts is None:
            stale += 1
            continue
        age = now - ts
        if age <= ttl_seconds:
            fresh += 1
        else:
            stale += 1
        if oldest_ts is None or ts < oldest_ts:
            oldest_ts = ts
            oldest = fetched_at
        if newest_ts is None or ts > newest_ts:
            newest_ts = ts
            newest = fetched_at
    market_total = conn.execute("SELECT COUNT(*) AS n FROM symbol_market").fetchone()
    symbols_total = conn.execute(
        "SELECT COUNT(DISTINCT symbol) AS n FROM symbols"
    ).fetchone()
    tracked = int(symbols_total["n"] or 0) if symbols_total else 0
    present = len(rows)
    return {
        "trackedSymbols": tracked,
        "withBlob": present,
        "missing": max(0, tracked - present),
        "fresh": fresh,
        "stale": stale,
        "ttlSeconds": float(ttl_seconds),
        "oldestFetchedAt": oldest,
        "newestFetchedAt": newest,
        "marketRows": int(market_total["n"] or 0) if market_total else 0,
    }


def build_cache_health_snapshot() -> dict[str, Any]:
    """Worker cycle status + Postgres fundamentals/news freshness for Consol."""
    import os

    from services.enrichment_warmer_service import (
        warm_chunk_size,
        warm_interval_seconds,
        warm_pause_seconds,
        warmer_enabled,
    )
    from services.market_data_service import MarketDataService
    from services.worker_status import worker_status_snapshot

    market = MarketDataService()
    with get_connection() as conn:
        price_row = conn.execute(
            """
            SELECT
                MAX(price_as_of) AS max_price_as_of,
                MAX(updated_at) AS max_updated_at,
                COUNT(*) FILTER (WHERE current_price IS NOT NULL) AS with_price
            FROM symbol_market
            """
        ).fetchone()
        daily_assessment = conn.execute(
            "SELECT value FROM app_meta WHERE key = %s",
            ("daily_assessment_last_date",),
        ).fetchone()
        fundamentals = _blob_age_summary(
            conn,
            "fundamentals_json",
            ttl_seconds=market.fundamentals_ttl_seconds(),
        )
        news = _blob_age_summary(
            conn,
            "news_json",
            ttl_seconds=market.news_ttl_seconds(),
        )

    workers = worker_status_snapshot()
    return {
        "workers": {
            "priceSync": workers.get("priceSync"),
            "enrichmentWarm": workers.get("enrichmentWarm"),
            "priceSyncIntervalSeconds": 300,
            "enrichmentWarmIntervalSeconds": warm_interval_seconds() if warmer_enabled() else None,
            "enrichmentWarmChunkSize": warm_chunk_size() if warmer_enabled() else None,
            "enrichmentWarmPauseSeconds": warm_pause_seconds() if warmer_enabled() else None,
            "enrichmentWarmerEnabled": warmer_enabled(),
            "dailyAssessmentLastDate": (
                daily_assessment["value"] if daily_assessment else None
            ),
        },
        "postgres": {
            "prices": {
                "source": "yahoo (background sync)",
                "destination": "symbol_market",
                "withPrice": int(price_row["with_price"] or 0) if price_row else 0,
                "maxPriceAsOf": price_row["max_price_as_of"] if price_row else None,
                "maxUpdatedAt": price_row["max_updated_at"] if price_row else None,
            },
            "fundamentals": {
                "source": "yahoo (+ finnhub backfill)",
                "destination": "symbol_market.fundamentals_json",
                "persistenceEnabled": market.fundamentals_persistence_enabled(),
                **fundamentals,
            },
            "news": {
                "source": os.environ.get("NEWS_PROVIDER", "").strip() or "finnhub|yfinance",
                "destination": "symbol_market.news_json",
                "persistenceEnabled": market.news_persistence_enabled(),
                **news,
            },
        },
        "servingModel": {
            "userEndpoints": (
                "cache-first (Postgres / in-process TTL); "
                "live fill on miss when ENRICHMENT_LIVE_FALLBACK=1"
            ),
            "backgroundWarm": "paced chunks; starred → held → watchlist",
            "priceSync": "live Yahoo every ~5 min into Postgres; clients read DB",
        },
    }
