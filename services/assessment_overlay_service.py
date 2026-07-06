"""Personalize a shared base assessment with per-user portfolio context.

Runs cheaply (rules-only) on top of the once-per-day ``symbol_assessment`` row.
Hard threshold triggers remain authoritative and override the base action.
"""

from __future__ import annotations

from typing import Any

from services.llm_client import LLMClient


class AssessmentOverlayService:
    def __init__(self, llm_client: LLMClient | None = None):
        self.llm_client = llm_client or LLMClient()

    def apply(self, base: dict[str, Any], personal_context: dict[str, Any]) -> dict[str, Any]:
        note_syntheses = personal_context.get("noteSyntheses") or []
        combined = self.llm_client.aggregate_note_syntheses(
            personal_context["symbol"],
            note_syntheses,
        )

        overlay_context = {
            **personal_context,
            "noteSynthesis": combined,
            "unsynthesizedNoteCount": personal_context.get("unsynthesizedNoteCount", 0),
        }
        hard = self.llm_client.hard_trigger(overlay_context)

        factors = [str(item) for item in (base.get("factors") or [])]
        rationale = str(base.get("rationale") or "").strip()
        action = str(base.get("action", "hold")).lower()
        confidence = str(base.get("confidence", "medium")).lower()
        action_source = base.get("actionSource") or "base_assessment"

        if hard is not None:
            action = hard["action"]
            confidence = hard["confidence"]
            action_source = "rule_hard_trigger"
            hard_line = hard.get("reason", "Personal threshold crossed.")
            if hard_line not in factors:
                factors.insert(0, hard_line)
            rationale = (
                f"{rationale} Personal threshold override: {hard_line}"
                if rationale
                else f"Personal threshold override: {hard_line}"
            )
        else:
            action, confidence, factors, rationale = self._apply_personal_rules(
                action,
                confidence,
                factors,
                rationale,
                overlay_context,
                combined,
            )
            if action_source == "base_assessment":
                action_source = "base_assessment+overlay"

        return {
            "action": action,
            "confidence": confidence,
            "rationale": rationale,
            "factors": factors or ["No active triggers."],
            "noteSynthesis": combined,
            "provider": base.get("provider", "rules"),
            "actionSource": action_source,
            "baseAssessmentDate": base.get("asOfDate"),
            "baseFromCache": base.get("fromCache"),
        }

    def _apply_personal_rules(
        self,
        action: str,
        confidence: str,
        factors: list[str],
        rationale: str,
        context: dict[str, Any],
        combined: dict[str, Any],
    ) -> tuple[str, str, list[str], str]:
        price = context.get("currentPrice")
        target = context.get("targetPrice")
        screening = context.get("screening") or {}
        unsynthesized = context.get("unsynthesizedNoteCount", 0)
        alerts = context.get("alerts") or []
        holding = context.get("holding")

        if unsynthesized:
            line = (
                f"{unsynthesized} note(s) not yet synthesized — run Synthesize on notes "
                "to guide assessment."
            )
            if line not in factors:
                factors.append(line)

        alert_types = {alert.get("type") for alert in alerts}
        if action == "hold" and "fib_proximity" in alert_types:
            action = "watch"
            factors.append("Price is near a key Fibonacci level (your alert).")
        elif action == "hold" and "screener_upside" in alert_types:
            action = "watch"
            factors.append("Stock screens with substantial upside to your target.")

        if combined.get("growthTrajectory"):
            note_line = f"Your notes: {combined['summary']}"
            if note_line not in factors:
                factors.append(note_line)
            for catalyst in combined.get("catalystsToWatch", [])[:2]:
                factors.append(
                    f"Watch {catalyst.get('period', 'upcoming')}: {catalyst.get('metric', 'growth')} "
                    f"({catalyst.get('threshold', '')})"
                )

        if combined.get("sentiment") == "bullish" and action == "hold":
            action = "watch"
            factors.append("Your stored note synthesis describes a bullish growth trajectory.")

        if target and price and target > price:
            upside = (target - price) / price * 100
            if upside > 30:
                if action == "hold":
                    action = "watch"
                line = f"Your personal target implies {upside:.1f}% upside."
                if line not in factors:
                    factors.append(line)

        analyst_target = context.get("analystTarget1y")
        if (
            analyst_target
            and price
            and analyst_target > price
            and screening.get("upsidePct", 0) > 20
            and action == "hold"
        ):
            factors.append(
                f"Analyst 1Y target implies {screening['upsidePct']:.1f}% upside."
            )

        if holding and holding.get("weightPct") is not None:
            factors.append(f"Position weight: {holding['weightPct']:.1f}% of portfolio.")

        if factors and rationale:
            personal_bits = [
                f for f in factors[-3:]
                if f.startswith("Your ") or f.startswith("Position weight")
            ]
            if personal_bits:
                rationale = f"{rationale} Personal overlay: {' '.join(personal_bits)}"

        return action, confidence, factors, rationale
