from typing import Any

from db.database import get_connection, get_current_user_id


class HoldingsService:
    def _ensure_symbol_exists(self, symbol: str, data: dict) -> None:
        from services.portfolio_service import PortfolioService

        if PortfolioService().get_symbol(symbol) is None:
            PortfolioService().upsert_symbol(symbol, data)

    def list_holdings(self) -> list[dict[str, Any]]:
        user_id = get_current_user_id()
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT h.symbol, h.quantity, h.cost_basis, h.purchase_date, h.account_name,
                       h.created_at, h.updated_at,
                       m.current_price, m.day_change_pct,
                       s.annual_dividend, m.analyst_target_1y, s.target_price
                FROM holdings h
                LEFT JOIN symbols s ON s.user_id = h.user_id AND s.symbol = h.symbol
                LEFT JOIN symbol_market m ON m.symbol = h.symbol
                WHERE h.user_id = %s
                ORDER BY h.symbol
                """,
                (user_id,),
            ).fetchall()
        return [self._row_to_holding(row) for row in rows]

    def get_holding(self, symbol: str) -> dict[str, Any] | None:
        symbol = symbol.upper()
        user_id = get_current_user_id()
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT h.symbol, h.quantity, h.cost_basis, h.purchase_date, h.account_name,
                       h.created_at, h.updated_at,
                       m.current_price, m.day_change_pct,
                       s.annual_dividend, m.analyst_target_1y, s.target_price
                FROM holdings h
                LEFT JOIN symbols s ON s.user_id = h.user_id AND s.symbol = h.symbol
                LEFT JOIN symbol_market m ON m.symbol = h.symbol
                WHERE h.user_id = %s AND h.symbol = %s
                """,
                (user_id, symbol),
            ).fetchone()
        return self._row_to_holding(row) if row else None

    def upsert_holding(self, symbol: str, data: dict[str, Any]) -> dict[str, Any]:
        symbol = symbol.upper()
        self._ensure_symbol_exists(symbol, data)

        quantity = float(data.get("quantity", data.get("shares", 0)) or 0)
        if quantity <= 0:
            self.delete_holding(symbol)
            return None

        cost_basis = data.get("cost_basis", data.get("costBasis"))
        cost_basis = float(cost_basis) if cost_basis not in (None, "") else None
        account_name = data.get("account_name", data.get("accountName"))
        purchase_date = data.get("purchase_date", data.get("purchaseDate"))
        if purchase_date is not None:
            purchase_date = str(purchase_date).strip()[:10] or None

        user_id = get_current_user_id()
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO holdings (user_id, symbol, quantity, cost_basis, purchase_date, account_name)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT(user_id, symbol) DO UPDATE SET
                    quantity = excluded.quantity,
                    cost_basis = excluded.cost_basis,
                    purchase_date = COALESCE(excluded.purchase_date, holdings.purchase_date),
                    account_name = excluded.account_name,
                    updated_at = app_now_text()
                """,
                (user_id, symbol, quantity, cost_basis, purchase_date, account_name),
            )
            conn.commit()

        result = self.get_holding(symbol)
        assert result is not None
        return result

    def delete_holding(self, symbol: str) -> bool:
        symbol = symbol.upper()
        user_id = get_current_user_id()
        with get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM holdings WHERE user_id = %s AND symbol = %s",
                (user_id, symbol),
            )
            conn.commit()
            return cursor.rowcount > 0

    def prune_zero_quantity_holdings(self) -> int:
        """Remove stale holdings rows with zero shares (watch-only symbols)."""
        user_id = get_current_user_id()
        with get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM holdings WHERE user_id = %s AND COALESCE(quantity, 0) <= 0",
                (user_id,),
            )
            conn.commit()
            return cursor.rowcount

    def _row_to_holding(self, row) -> dict[str, Any]:
        quantity = row["quantity"] or 0
        current_price = row["current_price"]
        market_value = (
            round(quantity * current_price, 2) if current_price is not None else None
        )
        cost_basis = row["cost_basis"]
        total_cost = quantity * cost_basis if cost_basis is not None else None
        unrealized_gain = (
            round(market_value - total_cost, 2)
            if market_value is not None and total_cost is not None
            else None
        )
        gain_pct = (
            round(unrealized_gain / total_cost * 100, 2)
            if unrealized_gain is not None and total_cost
            else None
        )
        analyst_target = row["analyst_target_1y"]
        analyst_target_value = (
            round(quantity * analyst_target, 2)
            if analyst_target is not None
            else None
        )
        analyst_upside_pct = (
            round((analyst_target - current_price) / current_price * 100, 2)
            if analyst_target is not None and current_price
            else None
        )
        personal_target = row["target_price"]
        personal_target_value = (
            round(quantity * personal_target, 2)
            if personal_target is not None
            else None
        )
        personal_upside_pct = (
            round((personal_target - current_price) / current_price * 100, 2)
            if personal_target is not None and current_price
            else None
        )
        weight_pct = None

        return {
            "symbol": row["symbol"],
            "quantity": quantity,
            "costBasis": cost_basis,
            "purchaseDate": row["purchase_date"],
            "accountName": row["account_name"],
            "currentPrice": current_price,
            "dayChangePct": row["day_change_pct"],
            "marketValue": market_value,
            "totalCost": total_cost,
            "unrealizedGain": unrealized_gain,
            "gainPct": gain_pct,
            "annualDividend": row["annual_dividend"],
            "analystTarget1y": analyst_target,
            "analystTargetValue": analyst_target_value,
            "analystUpsidePct": analyst_upside_pct,
            "personalTarget": personal_target,
            "personalTargetValue": personal_target_value,
            "personalUpsidePct": personal_upside_pct,
            "weightPct": weight_pct,
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }
