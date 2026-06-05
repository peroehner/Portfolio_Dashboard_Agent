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
                "SELECT * FROM symbols WHERE symbol = ?",
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
                "SELECT symbol FROM symbols WHERE symbol = ?",
                (symbol,),
            ).fetchone()

            if existing:
                conn.execute(
                    """
                    UPDATE symbols
                    SET current_price = ?, target_price = ?, buy_below = ?, sell_above = ?,
                        updated_at = datetime('now')
                    WHERE symbol = ?
                    """,
                    (
                        payload.get("current_price"),
                        payload.get("target_price"),
                        payload.get("buy_below"),
                        payload.get("sell_above"),
                        symbol,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO symbols (symbol, current_price, target_price, buy_below, sell_above)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        symbol,
                        payload.get("current_price"),
                        payload.get("target_price"),
                        payload.get("buy_below"),
                        payload.get("sell_above"),
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
                "DELETE FROM symbols WHERE symbol = ?",
                (symbol,),
            )
            conn.commit()
            return cursor.rowcount > 0

    def import_legacy_state(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        imported = []
        for symbol, details in state.items():
            if not isinstance(details, dict):
                continue
            imported.append(self.upsert_symbol(symbol, details))
        return imported

    def sync_prices(self, engine) -> dict[str, Any]:
        symbols = self.list_symbols()
        if not symbols:
            return {"updated": 0, "symbols": []}

        tickers = [item["symbol"] for item in symbols]
        live_prices = engine.fetch_market_data(tickers)
        updated = 0

        with get_connection() as conn:
            for symbol in tickers:
                price = live_prices.get(symbol)
                if price is not None:
                    conn.execute(
                        """
                        UPDATE symbols
                        SET current_price = ?, updated_at = datetime('now')
                        WHERE symbol = ?
                        """,
                        (price, symbol),
                    )
                    updated += 1
            conn.commit()

        return {"updated": updated, "symbols": self.list_symbols()}

    def get_screener_input(self) -> dict[str, dict[str, Any]]:
        """Shape expected by PortfolioEngine.run_screener."""
        portfolio = {}
        for symbol in self.list_symbols():
            portfolio[symbol["symbol"]] = {
                "currentPrice": symbol.get("currentPrice"),
                "targetPrice": symbol.get("targetPrice"),
                "buyBelow": symbol.get("buyBelow"),
                "sellAbove": symbol.get("sellAbove"),
            }
        return portfolio

    def _normalize_symbol_input(self, data: dict[str, Any]) -> dict[str, float | None]:
        mapping = {
            "current_price": data.get("current_price", data.get("currentPrice")),
            "target_price": data.get("target_price", data.get("targetPrice")),
            "buy_below": data.get("buy_below", data.get("buyBelow")),
            "sell_above": data.get("sell_above", data.get("sellAbove")),
        }
        normalized = {}
        for key, value in mapping.items():
            if value is None or value == "":
                normalized[key] = None
            else:
                normalized[key] = float(value)
        return normalized

    def _row_to_symbol(self, row, include_notes: bool) -> dict[str, Any]:
        symbol = {
            "symbol": row["symbol"],
            "currentPrice": row["current_price"],
            "targetPrice": row["target_price"],
            "buyBelow": row["buy_below"],
            "sellAbove": row["sell_above"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }
        if include_notes:
            symbol["notes"] = NotesService().list_notes(row["symbol"])
        return symbol
