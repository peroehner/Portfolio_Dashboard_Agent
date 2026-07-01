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
        # How close (in %) the price must be to a planned-trade threshold before
        # an "approaching" (near) alert fires ahead of the "reached" alert.
        self.trade_near_pct = float(os.environ.get("TRADE_NEAR_PCT", "5"))

    def list_alerts(
        self,
        symbol: str | None = None,
        status: str = "active",
        limit: int = 100,
        include_stale: bool = False,
    ) -> list[dict[str, Any]]:
        """Return alerts for the current user.

        ``include_stale`` additionally returns ``stale`` alerts alongside the
        requested ``status`` (used by the UI alert list, which shows both active
        and stale). ``superseded``/``dismissed`` are never included unless asked
        for explicitly via ``status``.
        """
        user_id = get_current_user_id()
        statuses = [status]
        if include_stale and "stale" not in statuses:
            statuses.append("stale")
        query = """
            SELECT id, symbol, alert_type, message, price, reference_value,
                   fib_level, status, created_at
            FROM alerts
            WHERE user_id = %s AND status = ANY(%s)
        """
        params: list[Any] = [user_id, statuses]

        if symbol:
            query += " AND symbol = %s"
            params.append(symbol.upper())

        # Active first, then stale; newest first within each group.
        query += (
            " ORDER BY CASE WHEN status = 'active' THEN 0 ELSE 1 END,"
            " created_at DESC LIMIT %s"
        )
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
        # Signatures whose triggering condition is TRUE this cycle. Collected in
        # _create_alert (called only when a condition holds) even when the insert
        # is skipped as a duplicate, so staleness can be derived reliably.
        true_signatures: set[tuple[str, str, float, str]] = set()
        for symbol_data in self.portfolio_service.list_symbols():
            created.extend(self._check_thresholds(symbol_data, true_signatures))
            created.extend(self._check_fib_proximity(symbol_data, true_signatures))
        created.extend(self._check_screener(engine, true_signatures))
        self._apply_staleness(true_signatures)
        return [alert for alert in created if alert is not None]

    @staticmethod
    def _signature(
        symbol: str,
        alert_type: str,
        reference_value: float | None,
        fib_level: str | None,
    ) -> tuple[str, str, float, str]:
        """Stable identity of an alert condition: symbol + type + reference +
        fib level. Mirrors the matching done in ``_active_alert_exists`` (NULL
        reference → -1, NULL fib_level → "") and rounds the reference so a value
        round-tripped through Postgres still matches the freshly-computed one."""
        ref = -1.0 if reference_value is None else round(float(reference_value), 4)
        return (str(symbol).upper(), alert_type, ref, fib_level or "")

    @staticmethod
    def _staleness_transitions(
        rows: list[dict[str, Any]],
        true_signatures: set[tuple[str, str, float, str]],
    ) -> dict[int, str]:
        """Pure decision step (no DB): given the current active/stale alert rows
        and the set of currently-true signatures, return ``{alert_id: new_status}``.

        - ``active`` whose condition is no longer true  → ``stale``.
        - ``stale`` whose condition is true again       → ``superseded`` (a fresh
          ``active`` was just (re)created for that signature, so the old stale row
          is retired — "supersede-and-recreate" revival).

        Rows that should keep their status are omitted from the result.
        """
        changes: dict[int, str] = {}
        for row in rows:
            sig = AlertsService._signature(
                row["symbol"], row["alert_type"], row["reference_value"], row["fib_level"]
            )
            is_true = sig in true_signatures
            status = row["status"]
            if status == "active" and not is_true:
                changes[row["id"]] = "stale"
            elif status == "stale" and is_true:
                changes[row["id"]] = "superseded"
        return changes

    def _apply_staleness(
        self, true_signatures: set[tuple[str, str, float, str]]
    ) -> dict[int, str]:
        user_id = get_current_user_id()
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, symbol, alert_type, reference_value, fib_level, status
                FROM alerts
                WHERE user_id = %s AND status IN ('active', 'stale')
                """,
                (user_id,),
            ).fetchall()
            changes = self._staleness_transitions(rows, true_signatures)
            for new_status in ("stale", "superseded"):
                ids = [aid for aid, st in changes.items() if st == new_status]
                if ids:
                    conn.execute(
                        "UPDATE alerts SET status = %s WHERE id = ANY(%s)",
                        (new_status, ids),
                    )
            conn.commit()
        return changes

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

    @staticmethod
    def _plan_clause(shares: float | None, *, stop_loss: bool = False) -> str:
        """The ' — plan: ...' fragment describing the planned action + quantity.

        Sign of ``shares`` encodes direction: >0 add/buy, <0 sell/trim. Returns
        an empty string when there is no quantity (None or 0) so the caller emits
        the generic "...trade level." message."""
        if not shares:
            return ""
        if shares > 0:
            return f" — plan: add {shares:g} shares."
        tag = " (stop-loss)" if stop_loss else ""
        return f" — plan: sell {abs(shares):g} shares{tag}."

    def _check_thresholds(
        self,
        symbol_data: dict[str, Any],
        true_signatures: set | None = None,
    ) -> list[dict[str, Any]]:
        created = []
        symbol = symbol_data["symbol"]
        price = symbol_data.get("currentPrice")
        trade_below_price = symbol_data.get("tradeBelowPrice")
        trade_below_shares = symbol_data.get("tradeBelowShares")
        trade_above_price = symbol_data.get("tradeAbovePrice")
        trade_above_shares = symbol_data.get("tradeAboveShares")

        if price is None:
            return created

        near = self.trade_near_pct / 100.0

        # Trade@Below: a price floor. Default direction Buy (add on the dip), but
        # a negative quantity makes it a stop-loss (sell on the way down).
        if trade_below_price is not None:
            if price <= trade_below_price:
                # REACHED — urgent.
                clause = self._plan_clause(
                    trade_below_shares, stop_loss=bool(trade_below_shares and trade_below_shares < 0)
                )
                msg = (
                    f"{symbol} reached your lower ${trade_below_price:.2f} trade level"
                    + (clause if clause else ".")
                )
                created.append(
                    self._create_alert(
                        symbol=symbol,
                        alert_type="trade_below",
                        message=msg,
                        price=price,
                        reference_value=trade_below_price,
                        true_signatures=true_signatures,
                    )
                )
            elif price <= trade_below_price * (1 + near):
                # APPROACHING — near.
                away_pct = (price - trade_below_price) / trade_below_price * 100
                clause = self._plan_clause(trade_below_shares)
                msg = (
                    f"{symbol} is {away_pct:.1f}% above your ${trade_below_price:.2f} buy level"
                    + (clause if clause else ".")
                )
                created.append(
                    self._create_alert(
                        symbol=symbol,
                        alert_type="trade_below_near",
                        message=msg,
                        price=price,
                        reference_value=trade_below_price,
                        true_signatures=true_signatures,
                    )
                )

        # Trade@Above: a price ceiling. Default direction Sell (trim into
        # strength), but a positive quantity makes it a planned add.
        if trade_above_price is not None:
            if price >= trade_above_price:
                # REACHED — urgent.
                clause = self._plan_clause(trade_above_shares)
                msg = (
                    f"{symbol} reached your upper ${trade_above_price:.2f} trade level"
                    + (clause if clause else ".")
                )
                created.append(
                    self._create_alert(
                        symbol=symbol,
                        alert_type="trade_above",
                        message=msg,
                        price=price,
                        reference_value=trade_above_price,
                        true_signatures=true_signatures,
                    )
                )
            elif price >= trade_above_price * (1 - near):
                # APPROACHING — near.
                away_pct = (trade_above_price - price) / trade_above_price * 100
                clause = self._plan_clause(trade_above_shares)
                msg = (
                    f"{symbol} is {away_pct:.1f}% below your ${trade_above_price:.2f} sell level"
                    + (clause if clause else ".")
                )
                created.append(
                    self._create_alert(
                        symbol=symbol,
                        alert_type="trade_above_near",
                        message=msg,
                        price=price,
                        reference_value=trade_above_price,
                        true_signatures=true_signatures,
                    )
                )

        return [alert for alert in created if alert is not None]

    def _check_fib_proximity(
        self,
        symbol_data: dict[str, Any],
        true_signatures: set | None = None,
    ) -> list[dict[str, Any]]:
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
            true_signatures=true_signatures,
        )
        return [alert] if alert is not None else []

    def _check_screener(
        self, engine, true_signatures: set | None = None
    ) -> list[dict[str, Any]]:
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
                true_signatures=true_signatures,
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
        true_signatures: set | None = None,
    ) -> dict[str, Any] | None:
        symbol = symbol.upper()
        # Reaching this point means the condition is currently TRUE; record the
        # signature before the dedupe short-circuit so staleness sees it even
        # when no new row is inserted.
        if true_signatures is not None:
            true_signatures.add(
                self._signature(symbol, alert_type, reference_value, fib_level)
            )
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
