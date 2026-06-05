from typing import Any

from db.database import get_connection


class HoldingsService:
    def _ensure_symbol_exists(self, symbol: str, data: dict) -> None:
        from services.portfolio_service import PortfolioService

        if PortfolioService().get_symbol(symbol) is None:
            PortfolioService().upsert_symbol(symbol, data)

    def list_holdings(self) -> list[dict[str, Any]]:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT h.symbol, h.quantity, h.cost_basis, h.account_name,
                       h.created_at, h.updated_at, s.current_price
                FROM holdings h
                LEFT JOIN symbols s ON s.symbol = h.symbol
                ORDER BY h.symbol
                """
            ).fetchall()
        return [self._row_to_holding(row) for row in rows]

    def get_holding(self, symbol: str) -> dict[str, Any] | None:
        symbol = symbol.upper()
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT h.symbol, h.quantity, h.cost_basis, h.account_name,
                       h.created_at, h.updated_at, s.current_price
                FROM holdings h
                LEFT JOIN symbols s ON s.symbol = h.symbol
                WHERE h.symbol = ?
                """,
                (symbol,),
            ).fetchone()
        return self._row_to_holding(row) if row else None

    def upsert_holding(self, symbol: str, data: dict[str, Any]) -> dict[str, Any]:
        symbol = symbol.upper()
        self._ensure_symbol_exists(symbol, data)

        quantity = float(data.get("quantity", data.get("shares", 0)) or 0)
        cost_basis = data.get("cost_basis", data.get("costBasis"))
        cost_basis = float(cost_basis) if cost_basis not in (None, "") else None
        account_name = data.get("account_name", data.get("accountName"))

        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO holdings (symbol, quantity, cost_basis, account_name)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    quantity = excluded.quantity,
                    cost_basis = excluded.cost_basis,
                    account_name = excluded.account_name,
                    updated_at = datetime('now')
                """,
                (symbol, quantity, cost_basis, account_name),
            )
            conn.commit()

        result = self.get_holding(symbol)
        assert result is not None
        return result

    def delete_holding(self, symbol: str) -> bool:
        symbol = symbol.upper()
        with get_connection() as conn:
            cursor = conn.execute("DELETE FROM holdings WHERE symbol = ?", (symbol,))
            conn.commit()
            return cursor.rowcount > 0

    def _row_to_holding(self, row) -> dict[str, Any]:
        quantity = row["quantity"] or 0
        current_price = row["current_price"]
        market_value = quantity * current_price if current_price is not None else None
        cost_basis = row["cost_basis"]
        total_cost = quantity * cost_basis if cost_basis is not None else None
        unrealized_gain = (
            market_value - total_cost
            if market_value is not None and total_cost is not None
            else None
        )
        weight_pct = None

        return {
            "symbol": row["symbol"],
            "quantity": quantity,
            "costBasis": cost_basis,
            "accountName": row["account_name"],
            "currentPrice": current_price,
            "marketValue": market_value,
            "totalCost": total_cost,
            "unrealizedGain": unrealized_gain,
            "weightPct": weight_pct,
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }
