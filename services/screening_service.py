import os
from typing import Any

from services.alerts_service import AlertsService
from services.fib_service import FibService
from services.holdings_service import HoldingsService
from services.notes_service import NotesService
from services.portfolio_service import PortfolioService
from services.technical_service import TechnicalService


class ScreeningService:
    def __init__(self):
        self.portfolio_service = PortfolioService()
        self.holdings_service = HoldingsService()
        self.alerts_service = AlertsService()
        self.notes_service = NotesService()
        self.fib_service = FibService()
        self.technical_service = TechnicalService()
        self.fib_proximity_pct = float(os.environ.get("FIB_PROXIMITY_PCT", "1.0"))

    def run_screen(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        from services.assessment_service import ASSESSMENT_TECHNICALS, AssessmentService
        from services.inspector_service import build_symbol_recommendation

        filters = filters or {}
        results = []
        assessment_service = AssessmentService()

        symbols_data = self.portfolio_service.list_symbols()
        # Confluence rides the same cached price history the Patterns & Tech Signals
        # tab uses, computed in parallel so both tabs show an identical Tech Stance.
        charts = self._charts_for(symbols_data) if ASSESSMENT_TECHNICALS else {}

        for symbol_data in symbols_data:
            symbol = symbol_data["symbol"]
            row = self._score_symbol(symbol_data)
            self._apply_confluence_stance(row, charts.get(symbol))
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
            latest = assessments[0] if assessments else None
            row["assessedAt"] = latest.get("createdAt") if latest else None
            row["rationale"] = latest.get("rationale") if latest else None
            if self._passes_filters(row, filters):
                results.append(row)

        sort_key = filters.get("sort", "score")
        reverse = filters.get("order", "desc") != "asc"
        results.sort(key=lambda item: item.get(sort_key) or 0, reverse=reverse)
        return results

    def fib_proximity_map(self) -> list[dict[str, Any]]:
        """Per-symbol Fibonacci proximity enriched with the detected chart pattern,
        trend-wave count, and the technical stance — the data behind the
        "Patterns & Tech Signals" view."""
        from services.assessment_service import ASSESSMENT_TECHNICALS
        from services.inspector_service import build_technical_advisory

        symbols_data = [
            s for s in self.portfolio_service.list_symbols() if s.get("currentPrice") is not None
        ]

        charts = self._charts_for(symbols_data) if ASSESSMENT_TECHNICALS else {}

        rows = []
        for symbol_data in symbols_data:
            price = symbol_data["currentPrice"]
            symbol = symbol_data["symbol"]
            closest = self.fib_service.closest_level(symbol, price)
            fib = closest["fib"] if closest else self.fib_service.get_levels(symbol)
            advisory = build_technical_advisory(price, fib, closest)
            confluence = self._confluence_summary(charts.get(symbol))
            # Confluence agent (Phase 3) drives the Tech Stance when available; the
            # Fib-position advisory remains the fallback for symbols without enough
            # history to fuse.
            tech_stance = confluence["bias"] if confluence else advisory.get("stance")
            tech_message = confluence["message"] if confluence else advisory.get("message")
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
                    "pattern": self._top_pattern(charts.get(symbol)),
                    "trends": self._trend_summary(charts.get(symbol)),
                    "volume": self._volume_summary(charts.get(symbol)),
                    "confluence": confluence,
                    "techStance": tech_stance,
                    "techStanceMessage": tech_message,
                    "fibStance": advisory.get("stance"),
                }
            )
        rows.sort(
            key=lambda item: item["distancePct"] if item["distancePct"] is not None else 999,
        )
        return rows

    @staticmethod
    def _top_pattern(chart: dict[str, Any] | None) -> dict[str, Any] | None:
        patterns = (chart or {}).get("patterns") or []
        if not patterns:
            return None
        p = patterns[0]
        key = p.get("keyLevel") or {}
        validation = p.get("validation") or {}
        return {
            "name": p.get("name"),
            "type": p.get("type"),
            "status": p.get("status"),
            "confidence": p.get("confidence"),
            "keyLabel": key.get("label"),
            "neckline": key.get("price"),
            "target": p.get("target"),
            "validation": {
                "verdict": validation.get("verdict"),
                "score": validation.get("score"),
            } if validation else None,
        }

    @staticmethod
    def _trend_summary(chart: dict[str, Any] | None) -> dict[str, Any] | None:
        waves = (chart or {}).get("trendWaves") or []
        if not waves:
            return None
        ups = sum(1 for w in waves if w.get("direction") == "up")
        downs = sum(1 for w in waves if w.get("direction") == "down")
        return {"legs": len(waves), "ups": ups, "downs": downs}

    @staticmethod
    def _volume_summary(chart: dict[str, Any] | None) -> dict[str, Any] | None:
        """Compact liquidity context for the Patterns & Tech Signals table:
        relative volume, regime, and the Point of Control."""
        chart = chart or {}
        vol = chart.get("volume") or {}
        profile = chart.get("volumeProfile") or {}
        if not vol and not profile:
            return None
        return {
            "rvol": vol.get("rvol"),
            "state": vol.get("state"),
            "trend": vol.get("trend"),
            "poc": profile.get("poc"),
            "priceNode": (profile.get("priceNode") or {}).get("node"),
        }

    @staticmethod
    def _charts_for(symbols_data: list[dict[str, Any]]) -> dict[str, dict[str, Any] | None]:
        """Fetch computed charts (patterns + volume + confluence) for each symbol in
        parallel on the shared, persistent yfinance worker pool. Chart data is
        derived from cached price history and is user-independent, so the same
        results back both the Screening and Patterns & Tech Signals tabs."""
        from services.market_cache import yf_pool
        from services.technical_signals_service import TechnicalSignalsService

        charts: dict[str, dict[str, Any] | None] = {}
        symbols = [s["symbol"] for s in symbols_data if s.get("symbol")]
        if not symbols:
            return charts
        tsvc = TechnicalSignalsService()
        for symbol, chart in zip(symbols, yf_pool.map(tsvc.get_chart, symbols)):
            charts[symbol] = chart
        return charts

    def _apply_confluence_stance(
        self, row: dict[str, Any], chart: dict[str, Any] | None
    ) -> None:
        """Overlay the Confluence agent's fused bias onto a screening row so the
        Tech Stance matches the Patterns & Tech Signals tab. Falls back to the
        existing Fib-position stance when there isn't enough history to fuse."""
        confluence = self._confluence_summary(chart)
        row["confluence"] = confluence
        row["fibStance"] = row.get("techStance")
        if confluence:
            row["techStance"] = confluence["bias"]
            row["techStanceMessage"] = confluence["message"]

    @staticmethod
    def _confluence_summary(chart: dict[str, Any] | None) -> dict[str, Any] | None:
        """Compact fused-bias context for the Patterns & Tech Signals table:
        the Confluence agent's bias, strength, and agreement tally."""
        conf = (chart or {}).get("confluence")
        if not conf:
            return None
        return {
            "bias": conf.get("bias"),
            "score": conf.get("score"),
            "score100": conf.get("score100"),
            "strength": conf.get("strength"),
            "agreeCount": conf.get("agreeCount"),
            "conflictCount": conf.get("conflictCount"),
            "totalSignals": conf.get("totalSignals"),
            "summary": conf.get("summary"),
            "message": conf.get("message"),
        }

    def _score_symbol(
        self,
        symbol_data: dict[str, Any],
        *,
        technical_advisory: dict[str, str] | None = None,
    ) -> dict[str, Any]:
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
        fib = self._resolve_fib(symbol) if price is not None else None
        if price is not None and fib:
            fib_closest = self.fib_service.closest_level(symbol, price, fib=fib)
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

        if technical_advisory is not None:
            tech_stance = technical_advisory["stance"]
        else:
            from services.inspector_service import compute_technical_advisory

            tech_stance = compute_technical_advisory(
                symbol,
                price,
                self.technical_service,
                self.fib_service,
            )["stance"]

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
            "noteCount": len(self.notes_service.list_notes(symbol)),
            "techStance": tech_stance,
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

    def _resolve_fib(self, symbol: str) -> dict[str, Any] | None:
        snapshot = self.technical_service.get_snapshot(symbol)
        fib = self.technical_service.fib_from_snapshot(symbol, snapshot)
        if fib:
            return fib
        return self.fib_service.get_levels(symbol)
