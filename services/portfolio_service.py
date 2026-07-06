from typing import Any

from db.database import get_connection, get_current_user_id, list_distinct_symbols
from services.market_data_service import MarketDataService
from services.notes_service import NotesService


class PortfolioService:
    SYMBOL_FIELDS = (
        "current_price",
        "target_price",
        "buy_below",
        "sell_above",
        "trade_below_price",
        "trade_below_shares",
        "trade_above_price",
        "trade_above_shares",
    )

    def list_symbols(self) -> list[dict[str, Any]]:
        user_id = get_current_user_id()
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT s.*,
                       m.current_price AS market_current_price,
                       m.day_change_pct AS market_day_change_pct,
                       m.price_as_of AS market_price_as_of,
                       m.analyst_target_1y AS market_analyst_target_1y,
                       m.analyst_target_low AS market_analyst_target_low,
                       m.analyst_target_high AS market_analyst_target_high
                FROM symbols s
                LEFT JOIN symbol_market m ON m.symbol = s.symbol
                WHERE s.user_id = %s
                ORDER BY s.symbol
                """,
                (user_id,),
            ).fetchall()
        return [self._row_to_symbol(row, include_notes=False) for row in rows]

    def get_symbol(self, symbol: str) -> dict[str, Any] | None:
        symbol = symbol.upper()
        user_id = get_current_user_id()
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT s.*,
                       m.current_price AS market_current_price,
                       m.day_change_pct AS market_day_change_pct,
                       m.price_as_of AS market_price_as_of,
                       m.analyst_target_1y AS market_analyst_target_1y,
                       m.analyst_target_low AS market_analyst_target_low,
                       m.analyst_target_high AS market_analyst_target_high
                FROM symbols s
                LEFT JOIN symbol_market m ON m.symbol = s.symbol
                WHERE s.user_id = %s AND s.symbol = %s
                """,
                (user_id, symbol),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_symbol(row, include_notes=True)

    def upsert_symbol(self, symbol: str, data: dict[str, Any]) -> dict[str, Any]:
        symbol = symbol.upper()
        user_id = get_current_user_id()
        payload = self._normalize_symbol_input(data)

        with get_connection() as conn:
            existing = conn.execute(
                "SELECT * FROM symbols WHERE user_id = %s AND symbol = %s",
                (user_id, symbol),
            ).fetchone()

            if existing:
                merged = {
                    "current_price": payload.get("current_price", existing["current_price"]),
                    "target_price": payload.get("target_price", existing["target_price"]),
                    "buy_below": payload.get("buy_below", existing["buy_below"]),
                    "sell_above": payload.get("sell_above", existing["sell_above"]),
                    "trade_below_price": payload.get(
                        "trade_below_price", existing["trade_below_price"]
                    ),
                    "trade_below_shares": payload.get(
                        "trade_below_shares", existing["trade_below_shares"]
                    ),
                    "trade_above_price": payload.get(
                        "trade_above_price", existing["trade_above_price"]
                    ),
                    "trade_above_shares": payload.get(
                        "trade_above_shares", existing["trade_above_shares"]
                    ),
                    "annual_dividend": payload.get("annual_dividend", existing["annual_dividend"]),
                    "analyst_target_1y": payload.get(
                        "analyst_target_1y", existing["analyst_target_1y"]
                    ),
                }
                if merged["trade_below_price"] is not None:
                    merged["buy_below"] = merged["trade_below_price"]
                if merged["trade_above_price"] is not None:
                    merged["sell_above"] = merged["trade_above_price"]
                conn.execute(
                    """
                    UPDATE symbols
                    SET current_price = %s, target_price = %s, buy_below = %s, sell_above = %s,
                        trade_below_price = %s, trade_below_shares = %s,
                        trade_above_price = %s, trade_above_shares = %s,
                        annual_dividend = %s, analyst_target_1y = %s, updated_at = app_now_text()
                    WHERE user_id = %s AND symbol = %s
                    """,
                    (
                        merged["current_price"],
                        merged["target_price"],
                        merged["buy_below"],
                        merged["sell_above"],
                        merged["trade_below_price"],
                        merged["trade_below_shares"],
                        merged["trade_above_price"],
                        merged["trade_above_shares"],
                        merged["annual_dividend"],
                        merged["analyst_target_1y"],
                        user_id,
                        symbol,
                    ),
                )
            else:
                trade_below_price = payload.get("trade_below_price")
                trade_above_price = payload.get("trade_above_price")
                buy_below = (
                    trade_below_price
                    if trade_below_price is not None
                    else payload.get("buy_below")
                )
                sell_above = (
                    trade_above_price
                    if trade_above_price is not None
                    else payload.get("sell_above")
                )
                conn.execute(
                    """
                    INSERT INTO symbols (
                        user_id, symbol, current_price, target_price, buy_below, sell_above,
                        trade_below_price, trade_below_shares,
                        trade_above_price, trade_above_shares,
                        annual_dividend, analyst_target_1y
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        user_id,
                        symbol,
                        payload.get("current_price"),
                        payload.get("target_price"),
                        buy_below,
                        sell_above,
                        trade_below_price,
                        payload.get("trade_below_shares"),
                        trade_above_price,
                        payload.get("trade_above_shares"),
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
        user_id = get_current_user_id()
        with get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM symbols WHERE user_id = %s AND symbol = %s",
                (user_id, symbol),
            )
            conn.commit()
            return cursor.rowcount > 0

    def clear_portfolio(self) -> int:
        """Remove all symbols; cascades notes, alerts, assessments, and holdings."""
        user_id = get_current_user_id()
        with get_connection() as conn:
            cursor = conn.execute("DELETE FROM symbols WHERE user_id = %s", (user_id,))
            conn.commit()
            return cursor.rowcount

    def import_legacy_state(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        imported = []
        for symbol, details in state.items():
            if not isinstance(details, dict):
                continue
            imported.append(self.upsert_symbol(symbol, details))
        return imported

    def sync_prices(
        self,
        engine,
        *,
        refresh_targets: bool = True,
        symbols: list[str] | None = None,
        global_sync: bool = False,
    ) -> dict[str, Any]:
        if global_sync:
            tickers = list_distinct_symbols()
        else:
            all_symbols = self.list_symbols()
            if not all_symbols:
                return {"updated": 0, "symbols": []}
            if symbols:
                wanted = {str(s).upper() for s in symbols}
                tickers = [item["symbol"] for item in all_symbols if item["symbol"] in wanted]
            else:
                tickers = [item["symbol"] for item in all_symbols]

        if not tickers:
            return {"updated": 0, "symbols": self.list_symbols() if not global_sync else []}

        result = MarketDataService().sync_quotes(
            engine,
            tickers,
            refresh_targets=refresh_targets,
        )
        if global_sync:
            result["symbols"] = tickers
        else:
            result["symbols"] = self.list_symbols()
        return result

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
        # Price-like fields: rounded to 2dp.
        mappings = {
            "current_price": ("current_price", "currentPrice", "price"),
            "target_price": ("target_price", "targetPrice"),
            "buy_below": ("buy_below", "buyBelow"),
            "sell_above": ("sell_above", "sellAbove"),
            "trade_below_price": ("trade_below_price", "tradeBelowPrice"),
            "trade_above_price": ("trade_above_price", "tradeAbovePrice"),
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

        # Signed share-quantity fields: sign encodes direction (+ buy/add,
        # - sell/trim). Allow negatives; no abs/clamp. Rounded to 4dp.
        share_mappings = {
            "trade_below_shares": ("trade_below_shares", "tradeBelowShares"),
            "trade_above_shares": ("trade_above_shares", "tradeAboveShares"),
        }
        for field, keys in share_mappings.items():
            if not any(key in data for key in keys):
                continue
            value = next(data[key] for key in keys if key in data)
            if value is None or value == "":
                normalized[field] = None
            else:
                normalized[field] = round(float(value), 4)
        return normalized

    def _row_to_symbol(self, row, include_notes: bool) -> dict[str, Any]:
        keys = row.keys()
        current_price = row["market_current_price"] if row.get("market_current_price") is not None else row["current_price"]
        day_change_pct = (
            row["market_day_change_pct"]
            if row.get("market_day_change_pct") is not None
            else (row["day_change_pct"] if "day_change_pct" in keys else None)
        )
        price_as_of = (
            row["market_price_as_of"]
            if row.get("market_price_as_of") is not None
            else (row["price_as_of"] if "price_as_of" in keys else None)
        )
        analyst_target_1y = (
            row["market_analyst_target_1y"]
            if row.get("market_analyst_target_1y") is not None
            else row["analyst_target_1y"]
        )
        analyst_target_low = (
            row["market_analyst_target_low"]
            if row.get("market_analyst_target_low") is not None
            else (row["analyst_target_low"] if "analyst_target_low" in keys else None)
        )
        analyst_target_high = (
            row["market_analyst_target_high"]
            if row.get("market_analyst_target_high") is not None
            else (row["analyst_target_high"] if "analyst_target_high" in keys else None)
        )
        symbol = {
            "symbol": row["symbol"],
            "currentPrice": current_price,
            "dayChangePct": day_change_pct,
            "priceAsOf": price_as_of,
            "targetPrice": row["target_price"],
            "analystTarget1y": analyst_target_1y,
            "analystTargetLow": analyst_target_low,
            "analystTargetHigh": analyst_target_high,
            "buyBelow": row["buy_below"],
            "sellAbove": row["sell_above"],
            "tradeBelowPrice": row["trade_below_price"] if "trade_below_price" in keys else None,
            "tradeBelowShares": row["trade_below_shares"] if "trade_below_shares" in keys else None,
            "tradeAbovePrice": row["trade_above_price"] if "trade_above_price" in keys else None,
            "tradeAboveShares": row["trade_above_shares"] if "trade_above_shares" in keys else None,
            "annualDividend": row["annual_dividend"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }
        if include_notes:
            symbol["notes"] = NotesService().list_notes(row["symbol"])
        return symbol
