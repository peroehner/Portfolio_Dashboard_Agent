"""Shared market data — one row per ticker, deduplicated across users.

Phase A of commercialization: yfinance quotes are fetched once per symbol and
stored in ``symbol_market``. Per-user ``symbols`` rows keep personal fields
(targets, thresholds, dividends); market fields are mirrored on sync for
backward compatibility but reads prefer ``symbol_market``.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any

from db.database import get_connection, list_distinct_symbols

# Reuse the fundamentals in-memory TTL as the default DB cache window.
_DEFAULT_FUNDAMENTALS_TTL = float(os.environ.get("FUNDAMENTALS_CACHE_TTL_SECONDS", "21600"))


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _parse_utc_text(value: str | None) -> float | None:
    if not value:
        return None
    try:
        dt = datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return None


class MarketDataService:
    MARKET_FIELDS = (
        "current_price",
        "day_change_pct",
        "price_as_of",
        "analyst_target_1y",
        "analyst_target_low",
        "analyst_target_high",
        "company_name",
    )

    def list_tracked_symbols(self) -> list[str]:
        return list_distinct_symbols()

    def get_market(self, symbol: str) -> dict[str, Any] | None:
        symbol = symbol.upper()
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM symbol_market WHERE symbol = %s",
                (symbol,),
            ).fetchone()
        return self._row_to_market(row) if row else None

    def get_market_map(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        if not symbols:
            return {}
        wanted = [str(s).upper() for s in symbols]
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM symbol_market WHERE symbol = ANY(%s)",
                (wanted,),
            ).fetchall()
        return {row["symbol"]: self._row_to_market(row) for row in rows}

    def fundamentals_ttl_seconds(self) -> float:
        return float(
            os.environ.get(
                "SYMBOL_MARKET_FUNDAMENTALS_TTL_SECONDS",
                str(_DEFAULT_FUNDAMENTALS_TTL),
            )
        )

    def fundamentals_persistence_enabled(self) -> bool:
        return os.environ.get("SYMBOL_MARKET_FUNDAMENTALS", "1").strip().lower() not in (
            "0",
            "false",
            "no",
            "off",
        )

    def get_fundamentals(
        self,
        symbol: str,
        *,
        max_age_seconds: float | None = None,
    ) -> dict[str, Any] | None:
        """Return shared fundamentals when the persisted blob is still fresh."""
        if not self.fundamentals_persistence_enabled():
            return None
        symbol = symbol.upper()
        ttl = self.fundamentals_ttl_seconds() if max_age_seconds is None else max_age_seconds
        with get_connection() as conn:
            row = conn.execute(
                "SELECT fundamentals_json FROM symbol_market WHERE symbol = %s",
                (symbol,),
            ).fetchone()
        if not row or not row.get("fundamentals_json"):
            return None
        blob = row["fundamentals_json"]
        if isinstance(blob, str):
            try:
                blob = json.loads(blob)
            except json.JSONDecodeError:
                return None
        if not isinstance(blob, dict):
            return None
        fetched_at = _parse_utc_text(blob.get("fetchedAt"))
        if fetched_at is None or (time.time() - fetched_at) > ttl:
            return None
        fundamentals = blob.get("fundamentals")
        return fundamentals if isinstance(fundamentals, dict) else None

    def save_fundamentals(self, symbol: str, fundamentals: dict[str, Any]) -> None:
        """Persist fundamentals for a symbol (shared across all users)."""
        if not self.fundamentals_persistence_enabled():
            return
        if not fundamentals:
            return
        symbol = symbol.upper()
        payload = {
            "fundamentals": fundamentals,
            "fetchedAt": _utc_now_text(),
        }
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO symbol_market (symbol, fundamentals_json, updated_at)
                VALUES (%s, %s::jsonb, app_now_text())
                ON CONFLICT (symbol) DO UPDATE SET
                    fundamentals_json = EXCLUDED.fundamentals_json,
                    updated_at = app_now_text()
                """,
                (symbol, json.dumps(payload)),
            )
            conn.commit()

    def seed_from_import(self, symbol: str, data: dict[str, Any]) -> None:
        """Persist import-time market hints on symbol_market (shared, optional)."""
        symbol = symbol.upper()
        price = data.get("current_price")
        analyst_target = data.get("analyst_target_1y")
        if price is None and analyst_target is None:
            return
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO symbol_market (symbol, current_price, analyst_target_1y, updated_at)
                VALUES (%s, %s, %s, app_now_text())
                ON CONFLICT (symbol) DO UPDATE SET
                    current_price = COALESCE(EXCLUDED.current_price, symbol_market.current_price),
                    analyst_target_1y = COALESCE(EXCLUDED.analyst_target_1y, symbol_market.analyst_target_1y),
                    updated_at = app_now_text()
                """,
                (symbol, price, analyst_target),
            )
            conn.commit()

    def sync_quotes(
        self,
        engine,
        symbols: list[str],
        *,
        refresh_targets: bool = True,
    ) -> dict[str, Any]:
        """Fetch live quotes once and persist to symbol_market + all user rows."""
        tickers = sorted({str(s).upper() for s in symbols if s})
        if not tickers:
            return {"updated": 0, "updatedTargets": 0, "symbols": []}

        live_quotes = engine.fetch_market_quotes(
            tickers,
            include_analyst_targets=refresh_targets,
        )
        updated_prices = 0
        updated_targets = 0

        with get_connection() as conn:
            for symbol in tickers:
                quote = live_quotes.get(symbol) or {}
                price = quote.get("currentPrice")
                day_change_pct = quote.get("dayChangePct")
                analyst_target = quote.get("analystTarget1y")
                analyst_low = quote.get("analystTargetLow")
                analyst_high = quote.get("analystTargetHigh")
                as_of = quote.get("priceAsOf")
                company_name = quote.get("companyName") or quote.get("shortName")

                if not any(
                    value is not None
                    for value in (
                        price,
                        day_change_pct,
                        analyst_target,
                        analyst_low,
                        analyst_high,
                        as_of,
                    )
                ):
                    continue

                conn.execute(
                    """
                    INSERT INTO symbol_market (
                        symbol, current_price, day_change_pct, price_as_of,
                        analyst_target_1y, analyst_target_low, analyst_target_high,
                        company_name, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, app_now_text())
                    ON CONFLICT (symbol) DO UPDATE SET
                        current_price = COALESCE(EXCLUDED.current_price, symbol_market.current_price),
                        day_change_pct = COALESCE(EXCLUDED.day_change_pct, symbol_market.day_change_pct),
                        price_as_of = COALESCE(EXCLUDED.price_as_of, symbol_market.price_as_of),
                        analyst_target_1y = COALESCE(EXCLUDED.analyst_target_1y, symbol_market.analyst_target_1y),
                        analyst_target_low = COALESCE(EXCLUDED.analyst_target_low, symbol_market.analyst_target_low),
                        analyst_target_high = COALESCE(EXCLUDED.analyst_target_high, symbol_market.analyst_target_high),
                        company_name = COALESCE(EXCLUDED.company_name, symbol_market.company_name),
                        updated_at = app_now_text()
                    """,
                    (
                        symbol,
                        price,
                        day_change_pct,
                        as_of,
                        analyst_target,
                        analyst_low,
                        analyst_high,
                        company_name,
                    ),
                )

                if price is not None:
                    updated_prices += 1
                if analyst_target is not None:
                    updated_targets += 1
            conn.commit()

        return {
            "updated": updated_prices,
            "updatedTargets": updated_targets,
            "symbols": tickers,
        }

    def merge_market_into_symbol_row(self, row: dict[str, Any]) -> dict[str, Any]:
        """Overlay shared market fields onto a symbols row dict (SQL row or API shape)."""
        market = self.get_market(row["symbol"])
        if not market:
            return row
        merged = dict(row)
        for field in self.MARKET_FIELDS:
            market_value = market.get(field)
            if market_value is not None:
                merged[field] = market_value
        return merged

    def _row_to_market(self, row) -> dict[str, Any]:
        keys = row.keys()
        return {
            "symbol": row["symbol"],
            "current_price": row["current_price"],
            "dayChangePct": row["day_change_pct"] if "day_change_pct" in keys else None,
            "priceAsOf": row["price_as_of"] if "price_as_of" in keys else None,
            "analystTarget1y": row["analyst_target_1y"] if "analyst_target_1y" in keys else None,
            "analystTargetLow": row["analyst_target_low"] if "analyst_target_low" in keys else None,
            "analystTargetHigh": row["analyst_target_high"] if "analyst_target_high" in keys else None,
            "companyName": row["company_name"] if "company_name" in keys else None,
            "updatedAt": row["updated_at"],
        }
