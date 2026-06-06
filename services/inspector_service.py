import re
from typing import Any

from services.alerts_service import AlertsService
from services.assessment_service import AssessmentService
from services.fib_service import FibService
from services.holdings_service import HoldingsService
from services.portfolio_service import PortfolioService
from services.screening_service import ScreeningService


class InspectorService:
    def __init__(self):
        self.portfolio_service = PortfolioService()
        self.holdings_service = HoldingsService()
        self.alerts_service = AlertsService()
        self.assessment_service = AssessmentService()
        self.fib_service = FibService()
        self.screening_service = ScreeningService()

    def inspect(self, symbol: str) -> dict[str, Any] | None:
        symbol = symbol.upper()
        symbol_data = self.portfolio_service.get_symbol(symbol)
        if symbol_data is None:
            return None

        price = symbol_data.get("currentPrice")
        fib = self.fib_service.get_levels(symbol)
        nearest = (
            self.fib_service.nearest_level(symbol, price, self.screening_service.fib_proximity_pct)
            if price is not None
            else None
        )
        screen_row = self.screening_service._score_symbol(
            {**symbol_data, "notes": symbol_data.get("notes", [])}
        )
        assessments = self.assessment_service.list_assessments(symbol=symbol, limit=20)
        alerts = self.alerts_service.list_alerts(symbol=symbol, status="active")
        recommendation = self._build_recommendation(
            symbol_data, assessments, alerts, screen_row, nearest
        )

        return {
            "symbol": symbol,
            "quote": symbol_data,
            "holding": self.holdings_service.get_holding(symbol),
            "alerts": alerts,
            "fib": fib,
            "nearestFib": nearest,
            "screening": screen_row,
            "assessments": assessments,
            "recommendation": recommendation,
        }

    def _build_recommendation(
        self,
        symbol_data: dict[str, Any],
        assessments: list[dict[str, Any]],
        alerts: list[dict[str, Any]],
        screening: dict[str, Any],
        nearest_fib: dict[str, Any] | None,
    ) -> dict[str, Any]:
        notes = symbol_data.get("notes", [])
        syntheses = [note["synthesis"] for note in notes if note.get("synthesis")]
        latest = assessments[0] if assessments else None

        combined = {}
        if latest and latest.get("noteSynthesis"):
            combined = latest["noteSynthesis"]
        elif syntheses:
            combined = self._merge_syntheses(syntheses)

        thesis = combined.get("integratedSummary") or combined.get("summary") or ""
        sentiment = combined.get("sentiment") or "neutral"
        growth = (combined.get("growthTrajectory") or [])[:5]
        projections = (combined.get("revenueProjections") or [])[:3]
        catalysts = (combined.get("catalystsToWatch") or [])[:5]

        action = latest["action"] if latest else "hold"
        confidence = latest["confidence"] if latest else "medium"
        rationale = (
            latest["rationale"]
            if latest
            else "Synthesize your notes, then run Assess Symbol to generate a recommendation."
        )

        drivers = self._clean_factors(latest.get("factors", []) if latest else [])
        if not drivers and thesis:
            drivers = [thesis]

        watch_items = []
        for catalyst in catalysts:
            period = catalyst.get("period") or "Upcoming"
            metric = catalyst.get("metric") or "Growth"
            threshold = catalyst.get("threshold") or ""
            watch_items.append(f"{period}: {metric}" + (f" — target {threshold}" if threshold else ""))
        for alert in alerts[:3]:
            watch_items.append(alert["message"])
        if nearest_fib and nearest_fib.get("level"):
            watch_items.append(
                f"Price near Fib {nearest_fib['level'].get('label', '')} "
                f"({nearest_fib.get('distancePct', '—')}%)"
            )

        headline = self._headline_for_action(action, sentiment)

        return {
            "action": action,
            "confidence": confidence,
            "headline": headline,
            "rationale": rationale,
            "drivers": drivers[:6],
            "thesis": thesis,
            "sentiment": sentiment,
            "growthHighlights": growth,
            "projections": projections,
            "catalysts": catalysts,
            "watchItems": watch_items[:8],
            "assessedAt": latest.get("createdAt") if latest else None,
            "provider": latest.get("provider") if latest else None,
            "upsidePct": screening.get("upsidePct"),
        }

    @staticmethod
    def _merge_syntheses(syntheses: list[dict[str, Any]]) -> dict[str, Any]:
        summaries = [item.get("summary", "") for item in syntheses if item.get("summary")]
        growth = []
        projections = []
        catalysts = []
        sentiments = []
        for item in syntheses:
            growth.extend(item.get("growthTrajectory") or [])
            projections.extend(item.get("revenueProjections") or [])
            catalysts.extend(item.get("catalystsToWatch") or [])
            if item.get("sentiment"):
                sentiments.append(item["sentiment"])

        sentiment = "neutral"
        if sentiments.count("bullish") > sentiments.count("bearish"):
            sentiment = "bullish"
        elif sentiments.count("bearish") > sentiments.count("bullish"):
            sentiment = "bearish"

        return {
            "summary": " | ".join(summaries[:3]),
            "growthTrajectory": growth[:8],
            "revenueProjections": projections[:4],
            "catalystsToWatch": catalysts[:6],
            "sentiment": sentiment,
        }

    @staticmethod
    def _clean_factors(factors: list[Any]) -> list[str]:
        cleaned = []
        for factor in factors:
            if not isinstance(factor, str):
                continue
            text = factor.strip()
            if InspectorService._looks_like_identifier(text):
                continue
            cleaned.append(text)
        return cleaned

    @staticmethod
    def _looks_like_identifier(text: str) -> bool:
        if " " in text or len(text) < 8:
            return True
        if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9]*", text):
            return False
        return any(char.isupper() for char in text[1:])

    @staticmethod
    def _headline_for_action(action: str, sentiment: str) -> str:
        labels = {
            "buy": "Consider adding on confirmed setup",
            "sell": "Consider taking profits or reducing",
            "watch": "Monitor — catalysts approaching",
            "hold": "Maintain current positioning",
        }
        base = labels.get(action, "Review positioning")
        if sentiment == "bullish" and action in ("hold", "watch"):
            return f"{base} · bullish growth thesis"
        if sentiment == "bearish":
            return f"{base} · bearish notes flagged"
        return base
