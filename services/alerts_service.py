import os
from typing import Any

from db.database import get_connection, get_current_user_id
from services.fib_roles import (
    build_fib_context,
    fib_context_from_alert,
    format_fib_proximity_message,
)
from services.fib_service import FibService
from services.holdings_service import HoldingsService
from services.one_yt_context import (
    ONE_YT_ALERT_FAMILY,
    build_one_yt_context,
    format_one_yt_message,
    is_one_yt_alert_type,
    lead_pattern,
    one_yt_context_from_alert,
    portfolio_median_upside,
    upside_pct,
)
from services.portfolio_service import PortfolioService


_TRADE_ALERT_TYPES = frozenset(
    {"trade_above", "trade_above_near", "trade_below", "trade_below_near"}
)


class AlertsService:
    def __init__(self):
        self.portfolio_service = PortfolioService()
        self.holdings_service = HoldingsService()
        self.fib_service = FibService()
        self.fib_proximity_pct = float(os.environ.get("FIB_PROXIMITY_PCT", "1.0"))
        # How close (in %) the price must be to a planned-trade threshold before
        # an "approaching" (near) alert fires ahead of the "reached" alert.
        self.trade_near_pct = float(os.environ.get("TRADE_NEAR_PCT", "5"))
        # Lonely 23.6% (shallow) Fib alerts are suppressed unless a trade gate
        # or pattern key-level is also live for the same symbol.
        self.suppress_lonely_shallow = os.environ.get(
            "FIB_ALERT_SUPPRESS_SHALLOW", "1"
        ).strip().lower() not in {"0", "false", "no"}
        # Screener upside gate (fraction): same default as engine.run_screener (30%).
        self.screener_upside_pct = float(os.environ.get("SCREENER_UPSIDE_PCT", "30"))

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
    def _format_plan_money(amount: float) -> str:
        """Whole-dollar money with sign: $52,300 or -$12,400."""
        rounded = int(round(float(amount)))
        sign = "-" if rounded < 0 else ""
        return f"{sign}${abs(rounded):,}"

    @staticmethod
    def _format_plan_gain(amount: float) -> str:
        """Signed gain fragment: (+$31,234) or (-$1,200)."""
        rounded = int(round(float(amount)))
        sign = "+" if rounded >= 0 else "-"
        return f"({sign}${abs(rounded):,})"

    @staticmethod
    def _format_exec_price(price: float) -> str:
        """Compact execution price: $261.5, $261.25, or $260."""
        value = float(price)
        if abs(value - round(value)) < 1e-9:
            return f"${int(round(value))}"
        text = f"{value:.4f}".rstrip("0").rstrip(".")
        return f"${text}"

    @staticmethod
    def _format_plan_qty(qty: float) -> str:
        value = float(qty)
        if abs(value - round(value)) < 1e-9:
            return f"{int(round(value))}"
        return f"{value:g}"

    @staticmethod
    def _plan_action_label(
        shares: float,
        held: float,
        *,
        stop_loss: bool = False,
    ) -> str:
        """Buy/Add/Sell/Trim label from planned qty vs shares currently held.

        - Buy 100                 — buy with no shares held
        - Add +100 (->300)        — buy while already holding
        - Sell 100                — sell exactly the held amount
        - Sell 100 ⚠              — sell with nothing held (oversell)
        - Trim -100 (->50)        — partial sell, position remains
        - Trim -100 ⚠             — sell exceeds held while some are owned
        """
        qty = abs(float(shares))
        held = max(0.0, float(held or 0))
        qty_txt = AlertsService._format_plan_qty(qty)
        stop = " (stop-loss)" if stop_loss and shares < 0 else ""

        if shares > 0:
            if held <= 0:
                return f"Buy {qty_txt}{stop}"
            after = held + qty
            return f"Add +{qty_txt} (-> {AlertsService._format_plan_qty(after)}){stop}"

        # Sell / trim
        if held <= 0:
            return f"Sell {qty_txt} ⚠{stop}"
        if qty > held + 1e-9:
            return f"Trim -{qty_txt} ⚠{stop}"
        if abs(qty - held) <= 1e-9:
            return f"Sell {qty_txt}{stop}"
        after = held - qty
        return f"Trim -{qty_txt} (-> {AlertsService._format_plan_qty(after)}){stop}"

    @staticmethod
    def _plan_clause(
        shares: float | None,
        *,
        stop_loss: bool = False,
        exec_price: float | None = None,
        cost_basis: float | None = None,
        held_shares: float | None = None,
    ) -> str:
        """The ' — Plan: ...' fragment describing the planned action + economics.

        Sign of ``shares`` encodes direction: >0 add/buy, <0 sell/trim. Returns
        an empty string when there is no quantity (None or 0) so the caller emits
        the generic "...trade level." message.

        Action wording depends on ``held_shares`` (Buy/Add/Sell/Trim). When
        ``exec_price`` is set, appends ``@price for Net Cash $…``. Sells also
        append ``(+$gain)`` when ``cost_basis`` is available.
        """
        if not shares:
            return ""
        qty = abs(float(shares))
        is_buy = shares > 0
        held = float(held_shares or 0)
        action = AlertsService._plan_action_label(
            float(shares), held, stop_loss=stop_loss
        )

        if exec_price is None or not isinstance(exec_price, (int, float)):
            return f" — Plan: {action}."

        exec_price = float(exec_price)
        if not (exec_price > 0):
            return f" — Plan: {action}."

        net_cash = qty * exec_price
        if is_buy:
            net_cash = -net_cash
        clause = (
            f" — Plan: {action} @"
            f"{AlertsService._format_exec_price(exec_price)} for Net Cash "
            f"{AlertsService._format_plan_money(net_cash)}"
        )
        if (
            not is_buy
            and cost_basis is not None
            and isinstance(cost_basis, (int, float))
        ):
            gain = (exec_price - float(cost_basis)) * qty
            clause += f" {AlertsService._format_plan_gain(gain)}"
        return clause + "."

    def _holding_context(self, symbol: str) -> tuple[float, float | None]:
        """Return (held_shares, cost_basis) for plan wording / gain calc."""
        holding = self.holdings_service.get_holding(symbol)
        if not holding:
            return 0.0, None
        qty = holding.get("quantity")
        held = float(qty) if isinstance(qty, (int, float)) else 0.0
        cost = holding.get("costBasis")
        if cost is None or not isinstance(cost, (int, float)):
            return held, None
        return held, float(cost)

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
        held_shares, cost_basis = self._holding_context(symbol)

        # Trade@Below: a price floor. Default direction Buy (add on the dip), but
        # a negative quantity makes it a stop-loss (sell on the way down).
        if trade_below_price is not None:
            if price <= trade_below_price:
                # REACHED — urgent.
                clause = self._plan_clause(
                    trade_below_shares,
                    stop_loss=bool(trade_below_shares and trade_below_shares < 0),
                    exec_price=price,
                    cost_basis=cost_basis,
                    held_shares=held_shares,
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
                clause = self._plan_clause(
                    trade_below_shares,
                    exec_price=price,
                    cost_basis=cost_basis,
                    held_shares=held_shares,
                )
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
                clause = self._plan_clause(
                    trade_above_shares,
                    exec_price=price,
                    cost_basis=cost_basis,
                    held_shares=held_shares,
                )
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
                clause = self._plan_clause(
                    trade_above_shares,
                    exec_price=price,
                    cost_basis=cost_basis,
                    held_shares=held_shares,
                )
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
        fib_ctx = build_fib_context(
            level=level,
            price=price,
            distance_pct=nearest["distancePct"],
            alert_proximity_pct=self.fib_proximity_pct,
        )
        if not self._should_emit_fib_alert(
            fib_ctx, symbol, price, true_signatures
        ):
            return []

        alert = self._create_alert(
            symbol=symbol,
            alert_type="fib_proximity",
            message=format_fib_proximity_message(symbol, price, fib_ctx),
            price=price,
            reference_value=level["price"],
            fib_level=level["label"],
            true_signatures=true_signatures,
        )
        return [alert] if alert is not None else []

    def _should_emit_fib_alert(
        self,
        fib_ctx: dict[str, Any],
        symbol: str,
        price: float,
        true_signatures: set | None,
    ) -> bool:
        """Gate lonely shallow (23.6%) alerts unless co-triggered."""
        if not self.suppress_lonely_shallow:
            return True
        if fib_ctx.get("role") != "shallow":
            return True
        if self._has_trade_co_trigger(symbol, true_signatures):
            return True
        if self._has_pattern_key_level_near(symbol, price):
            return True
        return False

    @staticmethod
    def _has_trade_co_trigger(symbol: str, true_signatures: set | None) -> bool:
        if not true_signatures:
            return False
        sym = str(symbol).upper()
        return any(
            sig_sym == sym and alert_type in _TRADE_ALERT_TYPES
            for sig_sym, alert_type, _ref, _fib in true_signatures
        )

    def _has_pattern_key_level_near(self, symbol: str, price: float) -> bool:
        """True when a detected pattern's key level sits within Fib proximity."""
        try:
            from services.technical_signals_service import TechnicalSignalsService

            signals = TechnicalSignalsService().get_signals(symbol)
        except Exception:  # noqa: BLE001
            return False
        if not signals:
            return False
        band = max(self.fib_proximity_pct, 1.0)
        for pattern in signals.get("patterns") or []:
            key = pattern.get("keyLevel") or {}
            key_price = key.get("price")
            if not isinstance(key_price, (int, float)) or not price:
                continue
            dist = abs(float(price) - float(key_price)) / float(price) * 100
            if dist <= band:
                return True
        return False

    def _check_screener(
        self, engine, true_signatures: set | None = None
    ) -> list[dict[str, Any]]:
        created = []
        screener_input = self.portfolio_service.get_screener_input()
        if not screener_input:
            return created

        median = portfolio_median_upside(screener_input)
        threshold = self.screener_upside_pct  # percent points, e.g. 30
        for symbol, details in screener_input.items():
            price = details.get("currentPrice")
            target = details.get("analystTarget1y") or details.get("targetPrice")
            pct = upside_pct(price, target)
            if pct is None or pct <= threshold:
                continue
            if not isinstance(price, (int, float)) or not isinstance(target, (int, float)):
                continue

            atr_pct, pattern = self._one_yt_tape_context(symbol)
            ctx = build_one_yt_context(
                price=float(price),
                target=float(target),
                upside=float(pct),
                portfolio_median=median,
                atr_pct=atr_pct,
                pattern=pattern,
            )
            alert = self._create_alert(
                symbol=symbol,
                alert_type=str(ctx.get("alertType") or "one_yt_watch"),
                message=format_one_yt_message(symbol, float(price), ctx),
                price=float(price),
                reference_value=float(target),
                true_signatures=true_signatures,
            )
            if alert is not None:
                alert["oneYt"] = ctx
                created.append(alert)
        return created

    def _one_yt_tape_context(
        self, symbol: str
    ) -> tuple[float | None, dict[str, Any] | None]:
        """ATR% + lead pattern from cached technical signals (best-effort)."""
        try:
            from services.technical_signals_service import TechnicalSignalsService

            signals = TechnicalSignalsService().get_signals(symbol)
        except Exception:  # noqa: BLE001
            return None, None
        if not signals:
            return None, None
        atr_pct = (signals.get("volatility") or {}).get("atrPct")
        if not isinstance(atr_pct, (int, float)):
            atr_pct = None
        pattern = lead_pattern(signals.get("patterns"))
        return atr_pct, pattern

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
            # Refresh stored text/price so plan economics stay current without
            # waiting for the condition to clear and re-fire.
            self._refresh_active_alert_message(
                symbol, alert_type, reference_value, fib_level, message, price
            )
            return None

        user_id = get_current_user_id()
        with get_connection() as conn:
            # Keep only the latest alert per kind: supersede any prior active
            # alerts of the same symbol + type before inserting the new one.
            # 1YT categories are one family — Chance→Stretch swaps must retire
            # siblings (and legacy screener_upside) so chips stay exclusive.
            if alert_type in ONE_YT_ALERT_FAMILY:
                conn.execute(
                    """
                    UPDATE alerts SET status = 'superseded'
                    WHERE user_id = %s AND symbol = %s AND status = 'active'
                      AND alert_type = ANY(%s)
                    """,
                    (user_id, symbol, list(ONE_YT_ALERT_FAMILY)),
                )
            else:
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

    def _refresh_active_alert_message(
        self,
        symbol: str,
        alert_type: str,
        reference_value: float | None,
        fib_level: str | None,
        message: str,
        price: float | None,
    ) -> None:
        user_id = get_current_user_id()
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE alerts
                SET message = %s, price = %s
                WHERE user_id = %s AND symbol = %s AND alert_type = %s AND status = 'active'
                  AND COALESCE(reference_value, -1) = COALESCE(%s, -1)
                  AND COALESCE(fib_level, '') = COALESCE(%s, '')
                  AND (message IS DISTINCT FROM %s OR price IS DISTINCT FROM %s)
                """,
                (
                    message,
                    price,
                    user_id,
                    symbol,
                    alert_type,
                    reference_value,
                    fib_level or "",
                    message,
                    price,
                ),
            )
            conn.commit()

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
        alert = {
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
        if alert["type"] == "fib_proximity":
            fib_ctx = fib_context_from_alert(alert)
            if fib_ctx:
                alert["fib"] = fib_ctx
        elif is_one_yt_alert_type(alert["type"]):
            one_yt = one_yt_context_from_alert(alert)
            if one_yt:
                alert["oneYt"] = one_yt
        return alert
