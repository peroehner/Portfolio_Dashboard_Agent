"""Shared market data — one row per ticker, deduplicated across users.

Phase A of commercialization: yfinance quotes are fetched once per symbol and
stored in ``symbol_market``. Per-user ``symbols`` rows keep personal fields
(targets, thresholds, dividends); market fields are mirrored on sync for
backward compatibility but reads prefer ``symbol_market``.
"""

from __future__ import annotations

from typing import Any

from db.database import get_connection, list_distinct_symbols


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
                    conn.execute(
                        """
                        UPDATE symbols
                        SET current_price = %s,
                            day_change_pct = COALESCE(%s, day_change_pct),
                            price_as_of = COALESCE(%s, price_as_of),
                            updated_at = app_now_text()
                        WHERE symbol = %s
                        """,
                        (price, day_change_pct, as_of, symbol),
                    )
                    updated_prices += 1
                if analyst_target is not None:
                    conn.execute(
                        """
                        UPDATE symbols
                        SET analyst_target_1y = %s, updated_at = app_now_text()
                        WHERE symbol = %s
                        """,
                        (analyst_target, symbol),
                    )
                    updated_targets += 1
                if analyst_low is not None or analyst_high is not None:
                    conn.execute(
                        """
                        UPDATE symbols
                        SET analyst_target_low = COALESCE(%s, analyst_target_low),
                            analyst_target_high = COALESCE(%s, analyst_target_high),
                            updated_at = app_now_text()
                        WHERE symbol = %s
                        """,
                        (analyst_low, analyst_high, symbol),
                    )
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
