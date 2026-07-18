"""Personalize a shared base assessment with per-user portfolio context.

Runs cheaply (rules-only) on top of the once-per-day ``symbol_assessment`` row.
Hard threshold triggers remain authoritative and override the base action.
"""

from __future__ import annotations

from typing import Any

from services.fib_roles import fib_context_from_alert
from services.llm_client import LLMClient
from services.one_yt_context import is_one_yt_alert_type, one_yt_context_from_alert


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
            factors.append(self._fib_alert_factor(alerts))
        elif action == "hold" and any(is_one_yt_alert_type(t) for t in alert_types):
            action = "watch"
            factors.append(self._one_yt_alert_factor(alerts))

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

    @staticmethod
    def _fib_alert_factor(alerts: list[dict[str, Any]]) -> str:
        """Role-aware SAI factor for the nearest fib_proximity alert."""
        fib_alerts = [a for a in alerts if a.get("type") == "fib_proximity"]
        if not fib_alerts:
            return "Price is near a key Fibonacci level (your alert)."

        def _dist(alert: dict[str, Any]) -> float:
            ctx = alert.get("fib") or fib_context_from_alert(alert) or {}
            dist = ctx.get("distancePct")
            return float(dist) if isinstance(dist, (int, float)) else 999.0

        best = min(fib_alerts, key=_dist)
        ctx = best.get("fib") or fib_context_from_alert(best) or {}
        role_name = ctx.get("roleName") or best.get("fibLevel") or "Fibonacci"
        label = ctx.get("label")
        title = (
            f"{label} {role_name}"
            if label and str(label) not in str(role_name)
            else str(role_name)
        )
        side = ctx.get("side")
        side_txt = f", currently {side} the level" if side in ("above", "below") else ""
        cue = ctx.get("cue")
        if cue:
            return f"Price is near the {title}{side_txt} (your Fib alert) — {cue}."
        return f"Price is near the {title}{side_txt} (your Fib alert)."

    @staticmethod
    def _one_yt_alert_factor(alerts: list[dict[str, Any]]) -> str:
        """Context-aware SAI factor for 1YT category alerts."""
        yt_alerts = [a for a in alerts if is_one_yt_alert_type(a.get("type"))]
        if not yt_alerts:
            return "Stock screens with substantial upside to 1YT (your alert)."

        def _upside(alert: dict[str, Any]) -> float:
            ctx = alert.get("oneYt") or one_yt_context_from_alert(alert) or {}
            pct = ctx.get("upsidePct")
            if isinstance(pct, (int, float)):
                return float(pct)
            return -1.0

        best = max(yt_alerts, key=_upside)
        msg = str(best.get("message") or "").replace("**", "").strip().rstrip(".")
        if "below 1YT" in msg or "portfolio median" in msg or "× ATR" in msg:
            return f"{msg} (your 1YT alert)."

        ctx = best.get("oneYt") or one_yt_context_from_alert(best) or {}
        upside = ctx.get("upsidePct")
        upside_txt = f"{float(upside):.1f}%" if isinstance(upside, (int, float)) else "large"
        bits = [f"1YT gap {upside_txt}"]
        mult = ctx.get("vsMedianMultiple")
        median = ctx.get("portfolioMedianPct")
        if isinstance(mult, (int, float)) and isinstance(median, (int, float)):
            bits.append(f"{mult:.1f}× portfolio median ({median:.0f}%)")
        pattern = ctx.get("pattern") or {}
        if pattern.get("name"):
            verdict = pattern.get("verdict")
            bits.append(f"{pattern['name']}" + (f" ({verdict})" if verdict else ""))
        units = ctx.get("atrUnits")
        if isinstance(units, (int, float)):
            bits.append(f"≈{units:.0f}× ATR")
        cue = ctx.get("cue")
        head = "; ".join(bits)
        if cue:
            return f"{head} (your 1YT alert) — {cue}."
        return f"{head} (your 1YT alert)."
