import os
from typing import Any

from services.alerts_service import AlertsService
from services.fib_service import FibService
from services.holdings_service import HoldingsService
from services.portfolio_service import PortfolioService


class ScreeningService:
    def __init__(self):
        self.portfolio_service = PortfolioService()
        self.holdings_service = HoldingsService()
        self.alerts_service = AlertsService()
        self.fib_service = FibService()
        self.fib_proximity_pct = float(os.environ.get("FIB_PROXIMITY_PCT", "1.0"))

    def run_screen(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        from services.assessment_service import AssessmentService
        from services.inspector_service import build_symbol_recommendation

        filters = filters or {}
        results = []
        assessment_service = AssessmentService()

        for symbol_data in self.portfolio_service.list_symbols():
            symbol = symbol_data["symbol"]
            row = self._score_symbol(symbol_data)
            fib_closest = row.pop("_fibClosest", None)
            full_symbol = self.portfolio_service.get_symbol(symbol)
            assessments = assessment_service.list_assessments(symbol, limit=20)
            alerts = self.alerts_service.list_alerts(symbol=symbol, status="active")
            nearest = None
            if (
                fib_closest is not None
                and fib_closest["distancePct"] <= self.fib_proximity_pct
            ):
                nearest = fib_closest
            rec = build_symbol_recommendation(
                full_symbol or symbol_data,
                assessments,
                alerts,
                row,
                nearest,
            )
            row["recommendation"] = {
                "action": rec.get("action") or "hold",
                "confidence": rec.get("confidence") or "medium",
                "sentiment": rec.get("sentiment") or "neutral",
            }
            if self._passes_filters(row, filters):
                results.append(row)

        sort_key = filters.get("sort", "score")
        reverse = filters.get("order", "desc") != "asc"
        results.sort(key=lambda item: item.get(sort_key) or 0, reverse=reverse)
        return results

    def fib_proximity_map(self) -> list[dict[str, Any]]:
        rows = []
        for symbol_data in self.portfolio_service.list_symbols():
            price = symbol_data.get("currentPrice")
            if price is None:
                continue
            symbol = symbol_data["symbol"]
            closest = self.fib_service.closest_level(symbol, price)
            fib = closest["fib"] if closest else self.fib_service.get_levels(symbol)
            rows.append(
                {
                    "symbol": symbol,
                    "currentPrice": price,
                    "nearestFib": closest["level"] if closest else None,
                    "distancePct": closest["distancePct"] if closest else None,
                    "withinBand": (
                        closest is not None
                        and closest["distancePct"] <= self.fib_proximity_pct
                    ),
                    "levels": fib.get("levels", []) if fib else [],
                    "swingHigh": fib.get("swingHigh") if fib else None,
                    "swingLow": fib.get("swingLow") if fib else None,
                }
            )
        rows.sort(
            key=lambda item: item["distancePct"] if item["distancePct"] is not None else 999,
        )
        return rows

    def _score_symbol(self, symbol_data: dict[str, Any]) -> dict[str, Any]:
        symbol = symbol_data["symbol"]
        price = symbol_data.get("currentPrice")
        target = symbol_data.get("analystTarget1y") or symbol_data.get("targetPrice")
        buy_below = symbol_data.get("buyBelow")
        sell_above = symbol_data.get("sellAbove")
        alerts = self.alerts_service.list_alerts(symbol=symbol, status="active")
        holding = self.holdings_service.get_holding(symbol)

        upside_pct = None
        if price and target and price > 0:
            upside_pct = round((target - price) / price * 100, 2)

        buy_distance_pct = None
        if price and buy_below and price > 0:
            buy_distance_pct = round((price - buy_below) / price * 100, 2)

        sell_distance_pct = None
        if price and sell_above and price > 0:
            sell_distance_pct = round((sell_above - price) / price * 100, 2)

        fib_closest = None
        nearest = None
        fib_distance = None
        if price is not None:
            fib_closest = self.fib_service.closest_level(symbol, price)
            if fib_closest:
                fib_distance = fib_closest["distancePct"]
                if fib_distance <= self.fib_proximity_pct * 3:
                    nearest = fib_closest

        score = 0.0
        flags = []
        if upside_pct is not None and upside_pct >= 30:
            score += 30
            flags.append("high_upside")
        if buy_below is not None and price is not None and price <= buy_below:
            score += 25
            flags.append("below_buy")
        if sell_above is not None and price is not None and price >= sell_above:
            score += 20
            flags.append("above_sell")
        if fib_distance is not None and fib_distance <= self.fib_proximity_pct:
            score += 15
            flags.append("fib_near")
        if alerts:
            score += min(len(alerts) * 5, 15)
            flags.append("active_alerts")

        return {
            "symbol": symbol,
            "currentPrice": price,
            "targetPrice": target,
            "analystTarget1y": symbol_data.get("analystTarget1y"),
            "buyBelow": buy_below,
            "sellAbove": sell_above,
            "upsidePct": upside_pct,
            "buyDistancePct": buy_distance_pct,
            "sellDistancePct": sell_distance_pct,
            "fibDistancePct": fib_distance,
            "nearestFib": nearest["level"] if nearest else None,
            "alertCount": len(alerts),
            "holding": holding,
            "flags": flags,
            "score": round(score, 2),
            "_fibClosest": fib_closest,
        }

    def _passes_filters(self, row: dict[str, Any], filters: dict[str, Any]) -> bool:
        if filters.get("minUpside") is not None:
            if row.get("upsidePct") is None or row["upsidePct"] < float(filters["minUpside"]):
                return False
        if filters.get("belowBuy") and not (row.get("buyBelow") and row.get("currentPrice", 0) <= row["buyBelow"]):
            return False
        if filters.get("nearFib") and not (row.get("fibDistancePct") is not None and row["fibDistancePct"] <= self.fib_proximity_pct):
            return False
        if filters.get("hasAlerts") and row.get("alertCount", 0) == 0:
            return False
        return True
