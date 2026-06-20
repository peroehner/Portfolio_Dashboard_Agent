from typing import Any

from db.database import get_connection
from services.notes_service import NotesService


class PortfolioService:
    SYMBOL_FIELDS = ("current_price", "target_price", "buy_below", "sell_above")

    def list_symbols(self) -> list[dict[str, Any]]:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM symbols ORDER BY symbol"
            ).fetchall()
        return [self._row_to_symbol(row, include_notes=False) for row in rows]

    def get_symbol(self, symbol: str) -> dict[str, Any] | None:
        symbol = symbol.upper()
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM symbols WHERE symbol = %s",
                (symbol,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_symbol(row, include_notes=True)

    def upsert_symbol(self, symbol: str, data: dict[str, Any]) -> dict[str, Any]:
        symbol = symbol.upper()
        payload = self._normalize_symbol_input(data)

        with get_connection() as conn:
            existing = conn.execute(
                "SELECT * FROM symbols WHERE symbol = %s",
                (symbol,),
            ).fetchone()

            if existing:
                merged = {
                    "current_price": payload.get("current_price", existing["current_price"]),
                    "target_price": payload.get("target_price", existing["target_price"]),
                    "buy_below": payload.get("buy_below", existing["buy_below"]),
                    "sell_above": payload.get("sell_above", existing["sell_above"]),
                    "annual_dividend": payload.get("annual_dividend", existing["annual_dividend"]),
                    "analyst_target_1y": payload.get(
                        "analyst_target_1y", existing["analyst_target_1y"]
                    ),
                }
                conn.execute(
                    """
                    UPDATE symbols
                    SET current_price = %s, target_price = %s, buy_below = %s, sell_above = %s,
                        annual_dividend = %s, analyst_target_1y = %s, updated_at = app_now_text()
                    WHERE symbol = %s
                    """,
                    (
                        merged["current_price"],
                        merged["target_price"],
                        merged["buy_below"],
                        merged["sell_above"],
                        merged["annual_dividend"],
                        merged["analyst_target_1y"],
                        symbol,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO symbols (
                        symbol, current_price, target_price, buy_below, sell_above,
                        annual_dividend, analyst_target_1y
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        symbol,
                        payload.get("current_price"),
                        payload.get("target_price"),
                        payload.get("buy_below"),
                        payload.get("sell_above"),
                        payload.get("annual_dividend"),
                        payload.get("analyst_target_1y"),
                    ),
                )
            conn.commit()

        result = self.get_symbol(symbol)
        assert result is not None
        return result

    def delete_symbol(self, symbol: str) -> bool:
        symbol = symbol.upper()
        with get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM symbols WHERE symbol = %s",
                (symbol,),
            )
            conn.commit()
            return cursor.rowcount > 0

    def clear_portfolio(self) -> int:
        """Remove all symbols; cascades notes, alerts, assessments, and holdings."""
        with get_connection() as conn:
            cursor = conn.execute("DELETE FROM symbols")
            conn.commit()
            return cursor.rowcount

    def import_legacy_state(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        imported = []
        for symbol, details in state.items():
            if not isinstance(details, dict):
                continue
            imported.append(self.upsert_symbol(symbol, details))
        return imported

    def sync_prices(self, engine, *, refresh_targets: bool = True) -> dict[str, Any]:
        symbols = self.list_symbols()
        if not symbols:
            return {"updated": 0, "symbols": []}

        tickers = [item["symbol"] for item in symbols]
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
                if price is not None:
                    conn.execute(
                        """
                        UPDATE symbols
                        SET current_price = %s,
                            day_change_pct = COALESCE(%s, day_change_pct),
                            updated_at = app_now_text()
                        WHERE symbol = %s
                        """,
                        (price, day_change_pct, symbol),
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
            conn.commit()

        return {
            "updated": updated_prices,
            "updatedTargets": updated_targets,
            "symbols": self.list_symbols(),
        }

    def get_screener_input(self) -> dict[str, dict[str, Any]]:
        """Shape expected by PortfolioEngine.run_screener."""
        portfolio = {}
        for symbol in self.list_symbols():
            portfolio[symbol["symbol"]] = {
                "currentPrice": symbol.get("currentPrice"),
                "targetPrice": symbol.get("targetPrice"),
                "analystTarget1y": symbol.get("analystTarget1y"),
                "buyBelow": symbol.get("buyBelow"),
                "sellAbove": symbol.get("sellAbove"),
            }
        return portfolio

    def _normalize_symbol_input(self, data: dict[str, Any]) -> dict[str, float | None]:
        normalized: dict[str, float | None] = {}
        mappings = {
            "current_price": ("current_price", "currentPrice", "price"),
            "target_price": ("target_price", "targetPrice"),
            "buy_below": ("buy_below", "buyBelow"),
            "sell_above": ("sell_above", "sellAbove"),
            "annual_dividend": ("annual_dividend", "annualDividend"),
            "analyst_target_1y": (
                "analyst_target_1y",
                "analystTarget1y",
                "target1y",
                "oneYearTarget",
            ),
        }
        for field, keys in mappings.items():
            if not any(key in data for key in keys):
                continue
            value = next(data[key] for key in keys if key in data)
            if value is None or value == "":
                normalized[field] = None
            else:
                normalized[field] = round(float(value), 2)
        return normalized

    def _row_to_symbol(self, row, include_notes: bool) -> dict[str, Any]:
        keys = row.keys()
        symbol = {
            "symbol": row["symbol"],
            "currentPrice": row["current_price"],
            "dayChangePct": row["day_change_pct"] if "day_change_pct" in keys else None,
            "targetPrice": row["target_price"],
            "analystTarget1y": row["analyst_target_1y"],
            "buyBelow": row["buy_below"],
            "sellAbove": row["sell_above"],
            "annualDividend": row["annual_dividend"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }
        if include_notes:
            symbol["notes"] = NotesService().list_notes(row["symbol"])
        return symbol
