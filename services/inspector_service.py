import re
from typing import Any

import yfinance as yf

from services.alerts_service import AlertsService
from services.assessment_service import AssessmentService
from services.fib_service import FibService
from services.holdings_service import HoldingsService
from services.portfolio_service import PortfolioService
from services.screening_service import ScreeningService
from services.technical_service import TechnicalService


class InspectorService:
    def __init__(self):
        self.portfolio_service = PortfolioService()
        self.holdings_service = HoldingsService()
        self.alerts_service = AlertsService()
        self.assessment_service = AssessmentService()
        self.fib_service = FibService()
        self.screening_service = ScreeningService()
        self.technical_service = TechnicalService()

    def inspect(self, symbol: str) -> dict[str, Any] | None:
        symbol = symbol.upper()
        symbol_data = self.portfolio_service.get_symbol(symbol)
        if symbol_data is None:
            return None

        price = symbol_data.get("currentPrice")
        technical_snapshot = self.technical_service.get_snapshot(symbol)
        fib = self.technical_service.fib_from_snapshot(symbol, technical_snapshot)
        if not fib:
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
        holding = self.holdings_service.get_holding(symbol)
        recommendation = self._build_recommendation(
            symbol_data, assessments, alerts, screen_row, nearest
        )

        return {
            "symbol": symbol,
            "quote": symbol_data,
            "holding": holding,
            "alerts": alerts,
            "fib": fib,
            "fibBlueprint": self._build_fib_blueprint(fib, technical_snapshot),
            "technicalSnapshot": technical_snapshot,
            "nearestFib": nearest,
            "screening": screen_row,
            "assessments": assessments,
            "recommendation": recommendation,
            "positionMechanics": self._position_mechanics(holding),
            "valuation": self._valuation_metrics(symbol, symbol_data, screen_row, holding),
            "trendWaves": self._trend_waves(symbol, technical_snapshot),
            "trendWaveSource": "import" if technical_snapshot and technical_snapshot.get("trends") else "none",
            "importedFibLevels": self.technical_service.fib_levels_list(technical_snapshot),
            "chartTimeline": self.technical_service.chart_timeline(symbol, technical_snapshot),
            "technicalAdvisory": self._technical_advisory(price, fib),
            "chartPoints": self._chart_points(symbol_data, holding, fib),
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
    def _safe_round(value: Any, digits: int = 2) -> float | None:
        if value in (None, ""):
            return None
        try:
            return round(float(value), digits)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_pct(value: Any) -> float | None:
        rounded = InspectorService._safe_round(value)
        if rounded is None:
            return None
        if abs(rounded) <= 1:
            return round(rounded * 100, 1)
        return rounded

    def _trend_waves(
        self,
        symbol: str,
        technical_snapshot: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        return self.technical_service.trend_waves_for_symbol(symbol, technical_snapshot)

    def _build_fib_blueprint(
        self,
        fib: dict[str, Any] | None,
        technical_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if not fib:
            return None
        palette = {
            "0% High": "#a78bfa",
            "38.2% Fib": "#3b82f6",
            "50.0% Center": "#f59e0b",
            "61.8% Golden": "#ef4444",
            "100% Base": "#9aa8bc",
        }
        blueprint_ratios = {
            0.382: ("fib-0.382", "38.2% Fib"),
            0.5: ("fib-0.5", "50.0% Center"),
            0.618: ("fib-0.618", "61.8% Golden"),
        }
        levels = [
            {
                "key": "high",
                "label": "0% High",
                "price": fib["swingHigh"],
                "color": palette["0% High"],
            }
        ]
        for level in fib.get("levels", []):
            ratio = level.get("ratio")
            mapping = blueprint_ratios.get(ratio)
            if not mapping:
                continue
            key, label = mapping
            levels.append(
                {
                    "key": key,
                    "label": label,
                    "price": level["price"],
                    "color": palette.get(label, "#9aa8bc"),
                }
            )
        levels.append(
            {
                "key": "base",
                "label": "100% Base",
                "price": fib["swingLow"],
                "color": palette["100% Base"],
            }
        )
        anchor_trend = fib.get("anchorTrend")
        if not anchor_trend and technical_snapshot:
            anchor_trend = self.technical_service._anchor_trend_label(technical_snapshot)
        return {
            "swingHigh": fib["swingHigh"],
            "swingLow": fib["swingLow"],
            "period": fib.get("period"),
            "levels": levels,
            "anchorTrend": anchor_trend,
            "anchorNote": fib.get("anchorNote"),
        }

    def _position_mechanics(self, holding: dict[str, Any] | None) -> dict[str, Any] | None:
        if not holding:
            return None
        entry_date = holding.get("purchaseDate") or holding.get("createdAt")
        if isinstance(entry_date, str) and len(entry_date) >= 10:
            entry_date = entry_date[:10]
        return {
            "entryDate": entry_date,
            "purchaseDate": holding.get("purchaseDate"),
            "sharesOwned": holding.get("quantity"),
            "entryCapital": holding.get("totalCost"),
            "totalGain": holding.get("unrealizedGain"),
            "totalGainPct": holding.get("gainPct"),
            "currentValue": holding.get("marketValue"),
            "costBasis": holding.get("costBasis"),
        }

    def _valuation_metrics(
        self,
        symbol: str,
        symbol_data: dict[str, Any],
        screening: dict[str, Any],
        holding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metrics: dict[str, Any] = {
            "pScore": screening.get("score"),
            "estDividend": symbol_data.get("annualDividend") or (holding or {}).get("annualDividend"),
            "trailingPe": None,
            "forwardPe": None,
            "pegRatio": None,
            "revenueGrowth": None,
            "operatingMargin": None,
        }
        try:
            info = yf.Ticker(symbol).info
            metrics.update(
                {
                    "trailingPe": self._safe_round(info.get("trailingPE")),
                    "forwardPe": self._safe_round(info.get("forwardPE")),
                    "pegRatio": self._safe_round(info.get("pegRatio")),
                    "revenueGrowth": self._safe_pct(info.get("revenueGrowth")),
                    "operatingMargin": self._safe_pct(info.get("operatingMargins")),
                }
            )
        except Exception:
            pass
        return metrics

    def _detect_trend_waves(self, symbol: str) -> list[dict[str, Any]]:
        try:
            history = yf.Ticker(symbol).history(period="6mo", auto_adjust=True)
        except Exception:
            return []
        if history.empty or len(history) < 12:
            return []

        closes = [float(value) for value in history["Close"].tolist()]
        dates = [index.strftime("%Y-%m-%d") for index in history.index]
        window = 3
        pivots: list[dict[str, Any]] = []
        for index in range(window, len(closes) - window):
            segment = closes[index - window : index + window + 1]
            price = closes[index]
            if price == max(segment):
                pivot_type = "peak"
            elif price == min(segment):
                pivot_type = "trough"
            else:
                continue
            pivots.append(
                {
                    "index": index,
                    "price": round(price, 2),
                    "date": dates[index],
                    "type": pivot_type,
                }
            )

        merged: list[dict[str, Any]] = []
        for pivot in pivots:
            if merged and merged[-1]["type"] == pivot["type"]:
                previous = merged[-1]
                if pivot["type"] == "peak" and pivot["price"] > previous["price"]:
                    merged[-1] = pivot
                elif pivot["type"] == "trough" and pivot["price"] < previous["price"]:
                    merged[-1] = pivot
                continue
            merged.append(pivot)

        waves: list[dict[str, Any]] = []
        for wave_index, pivot in enumerate(merged[:4], start=1):
            direction = "up" if pivot["type"] == "trough" else "down"
            if wave_index > 1:
                previous_price = merged[wave_index - 2]["price"]
                direction = "up" if pivot["price"] >= previous_price else "down"
            waves.append(
                {
                    "label": f"T{wave_index}",
                    "date": pivot["date"],
                    "price": pivot["price"],
                    "type": pivot["type"],
                    "direction": direction,
                }
            )
        return waves

    def _technical_advisory(
        self,
        price: float | None,
        fib: dict[str, Any] | None,
    ) -> dict[str, str]:
        if price is None or not fib:
            return {
                "stance": "Unknown",
                "message": "Insufficient technical data to assess support positioning.",
            }

        center_level = next(
            (level["price"] for level in fib.get("levels", []) if level.get("ratio") == 0.5),
            None,
        )
        nearest = self.fib_service.closest_level(fib["symbol"], price) if fib else None
        distance = nearest["distancePct"] if nearest else None

        if center_level is not None and price >= center_level:
            stance = "Strong"
            message = (
                f"Trading at ${price:,.2f}, comfortably above 50% technical support "
                f"level (${center_level:,.2f}). Highly bullish trend baseline."
            )
        elif distance is not None and distance < 2:
            stance = "Alert"
            level_label = nearest["level"]["label"] if nearest else "Fib"
            message = (
                f"Trading at ${price:,.2f}, within {distance:.2f}% of Fib {level_label}. "
                "Immediate retest or breakout setup — monitor closely."
            )
        elif center_level is not None:
            stance = "Cautious"
            message = (
                f"Trading at ${price:,.2f}, below 50% technical support "
                f"(${center_level:,.2f}). Watch for stabilization before adding risk."
            )
        else:
            stance = "Neutral"
            message = f"Trading at ${price:,.2f}. Monitor key Fibonacci boundaries for setup quality."

        return {"stance": stance, "message": message}

    def _chart_points(
        self,
        symbol_data: dict[str, Any],
        holding: dict[str, Any] | None,
        fib: dict[str, Any] | None,
    ) -> dict[str, Any]:
        current_price = symbol_data.get("currentPrice")
        target_price = (
            symbol_data.get("analystTarget1y")
            or symbol_data.get("targetPrice")
        )
        basis = None
        if holding and holding.get("costBasis") is not None:
            basis = holding["costBasis"]
        elif fib:
            basis = fib.get("swingLow")
        return {
            "basis": basis,
            "currentPrice": current_price,
            "consensusTarget": target_price,
        }

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
