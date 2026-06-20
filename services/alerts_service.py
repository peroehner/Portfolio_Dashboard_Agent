import os
from typing import Any

from db.database import get_connection, get_current_user_id
from services.fib_service import FibService
from services.portfolio_service import PortfolioService


class AlertsService:
    def __init__(self):
        self.portfolio_service = PortfolioService()
        self.fib_service = FibService()
        self.fib_proximity_pct = float(os.environ.get("FIB_PROXIMITY_PCT", "1.0"))

    def list_alerts(
        self,
        symbol: str | None = None,
        status: str = "active",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        user_id = get_current_user_id()
        query = """
            SELECT id, symbol, alert_type, message, price, reference_value,
                   fib_level, status, created_at
            FROM alerts
            WHERE user_id = %s AND status = %s
        """
        params: list[Any] = [user_id, status]

        if symbol:
            query += " AND symbol = %s"
            params.append(symbol.upper())

        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)

        with get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_alert(row) for row in rows]

    def dismiss_alert(self, alert_id: int) -> bool:
        user_id = get_current_user_id()
        with get_connection() as conn:
            cursor = conn.execute(
                "UPDATE alerts SET status = 'dismissed' "
                "WHERE id = %s AND user_id = %s AND status = 'active'",
                (alert_id, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def evaluate_all(self, engine) -> list[dict[str, Any]]:
        self._dedupe_active_alerts()
        created = []
        for symbol_data in self.portfolio_service.list_symbols():
            created.extend(self._check_thresholds(symbol_data))
            created.extend(self._check_fib_proximity(symbol_data))
        created.extend(self._check_screener(engine))
        return created

    def _dedupe_active_alerts(self) -> int:
        """Collapse active alerts to the newest one per symbol + type kind."""
        user_id = get_current_user_id()
        with get_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE alerts SET status = 'superseded'
                WHERE user_id = %s AND status = 'active'
                  AND id NOT IN (
                      SELECT MAX(id) FROM alerts
                      WHERE user_id = %s AND status = 'active'
                      GROUP BY symbol, alert_type
                  )
                """,
                (user_id, user_id),
            )
            conn.commit()
            return cursor.rowcount

    def _check_thresholds(self, symbol_data: dict[str, Any]) -> list[dict[str, Any]]:
        created = []
        symbol = symbol_data["symbol"]
        price = symbol_data.get("currentPrice")
        buy_below = symbol_data.get("buyBelow")
        sell_above = symbol_data.get("sellAbove")

        if price is None:
            return created

        if buy_below is not None and price <= buy_below:
            created.append(
                self._create_alert(
                    symbol=symbol,
                    alert_type="buy_below",
                    message=f"{symbol} at ${price:.2f} is at or below your buy-below level of ${buy_below:.2f}.",
                    price=price,
                    reference_value=buy_below,
                )
            )

        if sell_above is not None and price >= sell_above:
            created.append(
                self._create_alert(
                    symbol=symbol,
                    alert_type="sell_above",
                    message=f"{symbol} at ${price:.2f} is at or above your sell-above level of ${sell_above:.2f}.",
                    price=price,
                    reference_value=sell_above,
                )
            )

        return [alert for alert in created if alert is not None]

    def _check_fib_proximity(self, symbol_data: dict[str, Any]) -> list[dict[str, Any]]:
        symbol = symbol_data["symbol"]
        price = symbol_data.get("currentPrice")
        if price is None:
            return []

        nearest = self.fib_service.nearest_level(symbol, price, self.fib_proximity_pct)
        if nearest is None:
            return []

        level = nearest["level"]
        alert = self._create_alert(
            symbol=symbol,
            alert_type="fib_proximity",
            message=(
                f"{symbol} at ${price:.2f} is within {nearest['distancePct']:.2f}% of "
                f"the {level['label']} Fibonacci level at ${level['price']:.2f}."
            ),
            price=price,
            reference_value=level["price"],
            fib_level=level["label"],
        )
        return [alert] if alert is not None else []

    def _check_screener(self, engine) -> list[dict[str, Any]]:
        created = []
        screener_input = self.portfolio_service.get_screener_input()
        if not screener_input:
            return created

        for message in engine.run_screener(screener_input):
            symbol = message.split(" ", 1)[0]
            symbol_row = self.portfolio_service.get_symbol(symbol)
            reference = symbol_row.get("targetPrice") if symbol_row else None
            price = symbol_row.get("currentPrice") if symbol_row else None
            alert = self._create_alert(
                symbol=symbol,
                alert_type="screener_upside",
                message=message,
                price=price,
                reference_value=reference,
            )
            if alert is not None:
                created.append(alert)
        return created

    def _create_alert(
        self,
        symbol: str,
        alert_type: str,
        message: str,
        price: float | None,
        reference_value: float | None,
        fib_level: str | None = None,
    ) -> dict[str, Any] | None:
        symbol = symbol.upper()
        if self._active_alert_exists(symbol, alert_type, reference_value, fib_level):
            return None

        user_id = get_current_user_id()
        with get_connection() as conn:
            # Keep only the latest alert per kind: supersede any prior active
            # alerts of the same symbol + type before inserting the new one.
            conn.execute(
                """
                UPDATE alerts SET status = 'superseded'
                WHERE user_id = %s AND symbol = %s AND alert_type = %s AND status = 'active'
                """,
                (user_id, symbol, alert_type),
            )
            cursor = conn.execute(
                """
                INSERT INTO alerts (
                    user_id, symbol, alert_type, message, price, reference_value, fib_level
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (user_id, symbol, alert_type, message, price, reference_value, fib_level),
            )
            alert_id = cursor.fetchone()["id"]
            conn.commit()
            row = conn.execute(
                """
                SELECT id, symbol, alert_type, message, price, reference_value,
                       fib_level, status, created_at
                FROM alerts WHERE id = %s
                """,
                (alert_id,),
            ).fetchone()

        return self._row_to_alert(row) if row is not None else None

    def _active_alert_exists(
        self,
        symbol: str,
        alert_type: str,
        reference_value: float | None,
        fib_level: str | None = None,
    ) -> bool:
        user_id = get_current_user_id()
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT id FROM alerts
                WHERE user_id = %s AND symbol = %s AND alert_type = %s AND status = 'active'
                  AND COALESCE(reference_value, -1) = COALESCE(%s, -1)
                  AND COALESCE(fib_level, '') = COALESCE(%s, '')
                """,
                (user_id, symbol, alert_type, reference_value, fib_level),
            ).fetchone()
        return row is not None

    def _row_to_alert(self, row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "symbol": row["symbol"],
            "type": row["alert_type"],
            "message": row["message"],
            "price": row["price"],
            "referenceValue": row["reference_value"],
            "fibLevel": row["fib_level"],
            "status": row["status"],
            "createdAt": row["created_at"],
        }
