"""Personalize a shared base assessment with per-user portfolio context.

Default path: rules overlay, or Pass-2 LLM narrator when
``ASSESSMENT_OVERLAY_LLM=1`` and an LLM provider is active.

Hard threshold triggers remain authoritative and override the base action.
Pass 2 may only nudge Hold → Watch; it cannot flip Buy ↔ Sell from Fit.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from services.fib_roles import fib_context_from_alert
from services.harvest_score import scores_for_holding_context
from services.llm_client import LLMClient
from services.one_yt_context import is_one_yt_alert_type, one_yt_context_from_alert
from services.portfolio_intent import resolve_intent
from services.proposal_service import _fund_get

OVERLAY_LLM = os.environ.get("ASSESSMENT_OVERLAY_LLM", "1").lower() not in (
    "0",
    "false",
    "no",
    "off",
)

_CONF_RANK = {"high": 3, "medium": 2, "low": 1}
_HARVEST_ALERTS = {"tax_loss_candidate", "winner_trim_candidate", "harvest_imbalance"}

logger = logging.getLogger(__name__)


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

        if self._should_llm_overlay():
            try:
                packet = self.build_overlay_packet(base, overlay_context, combined, hard)
                raw = self.llm_client.generate_overlay_assessment(packet)
                return self._merge_llm_overlay(base, combined, hard, raw)
            except Exception as exc:  # noqa: BLE001 - overlay must not fail Assess
                logger.warning("Pass-2 overlay LLM failed, using rules overlay: %s", exc)
                result = self._apply_rules_overlay(base, overlay_context, combined, hard)
                result["llmFallback"] = True
                result["llmError"] = self.llm_client._classify_llm_error(exc)
                result["attemptedProvider"] = self.llm_client.active_provider()
                return result

        return self._apply_rules_overlay(base, overlay_context, combined, hard)

    def _should_llm_overlay(self) -> bool:
        if not OVERLAY_LLM:
            return False
        return self.llm_client.active_provider() in ("openai", "gemini")

    def _apply_rules_overlay(
        self,
        base: dict[str, Any],
        overlay_context: dict[str, Any],
        combined: dict[str, Any],
        hard: dict[str, Any] | None,
    ) -> dict[str, Any]:
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

    def _merge_llm_overlay(
        self,
        base: dict[str, Any],
        combined: dict[str, Any],
        hard: dict[str, Any] | None,
        raw: dict[str, Any],
    ) -> dict[str, Any]:
        locked_action = str((hard or {}).get("action") or base.get("action") or "hold").lower()
        llm_action = str(raw.get("action") or locked_action).lower()
        action = locked_action
        if hard is None and locked_action == "hold" and llm_action == "watch":
            action = "watch"

        base_conf = str(base.get("confidence") or "medium").lower()
        llm_conf = str(raw.get("confidence") or base_conf).lower()
        if hard is not None:
            confidence = str(hard.get("confidence") or "high").lower()
            action_source = "rule_hard_trigger"
        else:
            confidence = self._softer_confidence(base_conf, llm_conf)
            action_source = "base_assessment+overlay_llm"

        factors = [str(f) for f in (raw.get("factors") or []) if str(f).strip()]
        if hard is not None:
            hard_line = hard.get("reason", "Personal threshold crossed.")
            if hard_line not in factors:
                factors.insert(0, hard_line)
        rationale = str(raw.get("rationale") or base.get("rationale") or "").strip()
        watch_items = [str(w) for w in (raw.get("watchItems") or []) if str(w).strip()]
        note_synthesis = {**combined, "overlayWatchItems": watch_items} if watch_items else combined

        return {
            "action": action,
            "confidence": confidence,
            "rationale": rationale or "No overlay rationale provided.",
            "factors": factors or ["No active personal overlay factors."],
            "watchItems": watch_items,
            "noteSynthesis": note_synthesis,
            "provider": raw.get("provider") or base.get("provider", "rules"),
            "actionSource": action_source,
            "baseAssessmentDate": base.get("asOfDate"),
            "baseFromCache": base.get("fromCache"),
        }

    @staticmethod
    def _softer_confidence(base: str, llm: str) -> str:
        if llm not in _CONF_RANK:
            return base if base in _CONF_RANK else "medium"
        if base not in _CONF_RANK:
            return llm
        return llm if _CONF_RANK[llm] <= _CONF_RANK[base] else base

    def build_overlay_packet(
        self,
        base: dict[str, Any],
        context: dict[str, Any],
        combined: dict[str, Any],
        hard: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Slim book-constraint packet — no market technicals, news, or Score totals."""
        locked = str((hard or {}).get("action") or base.get("action") or "hold").lower()
        price = context.get("currentPrice")
        buy_below = context.get("buyBelow")
        sell_above = context.get("sellAbove")
        holding = self._slim_holding(context.get("holding"))
        screening = context.get("screening") or {}
        intent = self._intent_block(context, holding)
        harvest = self._harvest_facts(context, holding)
        prefs = self._slim_fit_prefs(context.get("fitPrefs") or {})
        portfolio_div = context.get("portfolioAnnualDividend")
        target_div = prefs.get("targetAnnualDividend")
        dividend = None
        if isinstance(target_div, (int, float)) or isinstance(portfolio_div, (int, float)):
            name_div = None
            if holding:
                per_sh = holding.get("annualDividend")
                qty = holding.get("quantity") or 0
                if isinstance(per_sh, (int, float)) and qty:
                    name_div = round(float(per_sh) * float(qty), 2)
            gap = None
            if isinstance(target_div, (int, float)) and isinstance(portfolio_div, (int, float)):
                gap = round(float(target_div) - float(portfolio_div), 2)
            dividend = {
                "targetAnnualDividend": target_div,
                "portfolioAnnualDividend": portfolio_div,
                "gapVsTarget": gap,
                "nameAnnualDividend": name_div,
            }

        return {
            "symbol": context.get("symbol"),
            "companyName": context.get("companyName"),
            "currentPrice": price,
            "baseAssessment": {
                "action": base.get("action"),
                "confidence": base.get("confidence"),
                "rationale": base.get("rationale"),
                "factors": (base.get("factors") or [])[:6],
                "asOfDate": base.get("asOfDate"),
            },
            "hardTrigger": hard,
            "constraints": {
                "lockedAction": locked,
                "allowHoldToWatch": hard is None and locked == "hold",
                "forbidBuySellFlip": True,
            },
            "personal": {
                "targetPrice": context.get("targetPrice"),
                "buyBelow": buy_below,
                "sellAbove": sell_above,
                "distanceToBuyBelowPct": self._distance_pct(price, buy_below),
                "distanceToSellAbovePct": self._distance_pct(price, sell_above),
                "holding": holding,
                "intent": intent,
                "fitPrefs": prefs,
                "dividend": dividend,
                "harvest": harvest,
                "alerts": self._slim_alerts(context.get("alerts") or []),
                "noteSynthesis": {
                    "summary": combined.get("summary"),
                    "sentiment": combined.get("sentiment"),
                    "growthTrajectory": (combined.get("growthTrajectory") or [])[:4],
                    "catalystsToWatch": (combined.get("catalystsToWatch") or [])[:4],
                },
                "unsynthesizedNoteCount": context.get("unsynthesizedNoteCount", 0),
                "analystUpsidePct": screening.get("upsidePct"),
                "fibDistancePct": screening.get("fibDistancePct"),
            },
        }

    @staticmethod
    def _distance_pct(price: Any, level: Any) -> float | None:
        if not isinstance(price, (int, float)) or not isinstance(level, (int, float)):
            return None
        if price == 0:
            return None
        return round((float(price) - float(level)) / float(price) * 100.0, 2)

    @staticmethod
    def _slim_holding(holding: dict[str, Any] | None) -> dict[str, Any] | None:
        if not holding:
            return None
        keys = ("quantity", "weightPct", "gainPct", "annualDividend", "costBasis")
        out = {k: holding.get(k) for k in keys if holding.get(k) is not None}
        return out or None

    @staticmethod
    def _slim_fit_prefs(prefs: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key in (
            "targetAnnualDividend",
            "volatilityPreference",
            "maxSingleNameWeightPct",
            "taxLotPreference",
        ):
            if prefs.get(key) is not None:
                out[key] = prefs[key]
        return out

    @staticmethod
    def _slim_alerts(alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        slim: list[dict[str, Any]] = []
        for alert in alerts[:8]:
            item: dict[str, Any] = {
                "type": alert.get("type"),
                "message": str(alert.get("message") or "")[:180],
            }
            if alert.get("type") in _HARVEST_ALERTS:
                item["harvest"] = True
            if alert.get("fib"):
                item["fib"] = {
                    k: alert["fib"].get(k)
                    for k in ("label", "roleName", "distancePct", "side", "cue")
                    if alert["fib"].get(k) is not None
                }
            if alert.get("oneYt"):
                item["oneYt"] = {
                    k: alert["oneYt"].get(k)
                    for k in ("upsidePct", "category", "cue")
                    if alert["oneYt"].get(k) is not None
                }
            slim.append(item)
        return slim

    def _intent_block(
        self, context: dict[str, Any], holding: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        screening = context.get("screening") or {}
        plan_row = {
            "tradeBelowPrice": screening.get("tradeBelowPrice") or context.get("buyBelow"),
            "tradeBelowShares": screening.get("tradeBelowShares")
            if screening.get("tradeBelowShares") is not None
            else context.get("tradeBelowShares"),
            "tradeAbovePrice": screening.get("tradeAbovePrice") or context.get("sellAbove"),
            "tradeAboveShares": screening.get("tradeAboveShares")
            if screening.get("tradeAboveShares") is not None
            else context.get("tradeAboveShares"),
        }
        from services.tax_trim_service import buy_plan_qty, sell_plan_qty
        from services.proposal_service import ProposalService

        buy_qty = buy_plan_qty(plan_row)
        sell_qty = sell_plan_qty(plan_row)
        held_qty = float((holding or {}).get("quantity") or 0)
        override = context.get("intentOverride") or (holding or {}).get("intentOverride")
        intent = resolve_intent(
            held=held_qty,
            buy_qty=buy_qty,
            sell_qty=sell_qty,
            buy_price=ProposalService._leg_price_for_side(plan_row, buy=True),
            sell_price=ProposalService._leg_price_for_side(plan_row, buy=False),
            override=override,
        )
        return {
            "code": intent.get("code"),
            "label": intent.get("label"),
            "source": intent.get("source"),
        }

    def _harvest_facts(
        self, context: dict[str, Any], holding: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if not holding:
            return None
        fundamentals = context.get("fundamentals") or {}
        high_52 = _fund_get(fundamentals, "high52w", "fiftyTwoWeekHigh", "week52High")
        screening = context.get("screening") or {}
        from services.tax_trim_service import buy_plan_qty, sell_plan_qty

        plan_row = {
            "tradeBelowPrice": screening.get("tradeBelowPrice") or context.get("buyBelow"),
            "tradeBelowShares": screening.get("tradeBelowShares"),
            "tradeAbovePrice": screening.get("tradeAbovePrice") or context.get("sellAbove"),
            "tradeAboveShares": screening.get("tradeAboveShares"),
        }
        facts = scores_for_holding_context(
            {
                "holding": holding,
                "currentPrice": context.get("currentPrice"),
                "analystTarget1y": context.get("analystTarget1y"),
                "personalTarget": context.get("targetPrice"),
                "high52w": high_52,
                "buyPlanQty": buy_plan_qty(plan_row),
                "sellPlanQty": sell_plan_qty(plan_row),
            }
        )
        return {
            "lossScore": round(float(facts.get("lossScore") or 0), 1),
            "trimScore": round(float(facts.get("trimScore") or 0), 1),
            "residualLossPct": facts.get("residualLossPct"),
            "peakPct": facts.get("peakPct"),
            "analystUpsidePct": facts.get("analystUpsidePct"),
            "personalUpsidePct": facts.get("personalUpsidePct"),
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
