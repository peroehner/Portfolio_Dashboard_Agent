"""Trading proposal scaffold — State / Trigger / Portfolio Fit.

Slice 1: heuristic scores from existing assess/inspector context.
Authority remains the assessment action until later iterations graduate scores.
See docs/PROPOSAL_FRAMEWORK.md.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = 1
STATE_MAX = 50
TRIGGER_MAX = 30
FIT_MAX = 20

# Soft concentration warning (not a hard veto until preferences land).
CONCENTRATION_WARN_PCT = 20.0
CONCENTRATION_VETO_PCT = 40.0

CONFIRMATION_REQUIRED = 2

# Placeholder keys for Portfolio Fit iterations (always present, values null until wired).
FIT_EXTENSION_KEYS = (
    "targetAnnualDividend",
    "volatilityPreference",
    "maxSingleNameWeightPct",
    "sectorCapPct",
    "taxLotPreference",
    "filterSetBias",
)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _round_score(value: float) -> int:
    return int(round(_clamp(value, 0, 100)))


class ProposalService:
    """Build a versioned proposal payload from assessment + portfolio context."""

    def build(
        self,
        *,
        symbol: str,
        action: str,
        confidence: str,
        rationale: str = "",
        factors: list[str] | None = None,
        action_source: str | None = None,
        context: dict[str, Any] | None = None,
        screening: dict[str, Any] | None = None,
        holding: dict[str, Any] | None = None,
        alerts: list[dict[str, Any]] | None = None,
        technical: dict[str, Any] | None = None,
        news_sentiment: dict[str, Any] | None = None,
        previous_actions: list[str] | None = None,
    ) -> dict[str, Any]:
        ctx = context or {}
        screening = screening if screening is not None else (ctx.get("screening") or {})
        holding = holding if holding is not None else ctx.get("holding")
        alerts = alerts if alerts is not None else (ctx.get("alerts") or [])
        technical = technical if technical is not None else ctx.get("technical")
        factors = [str(f) for f in (factors or [])]

        state = self._score_state(
            action=action,
            confidence=confidence,
            screening=screening,
            fundamentals=ctx.get("fundamentals") or {},
            note_factors=factors,
            upside_pct=screening.get("upsidePct"),
            target_price=ctx.get("targetPrice"),
            analyst_target=ctx.get("analystTarget1y"),
            current_price=ctx.get("currentPrice"),
        )
        trigger = self._score_trigger(
            action=action,
            action_source=action_source,
            alerts=alerts,
            screening=screening,
            technical=technical,
            news_sentiment=news_sentiment,
            buy_below=ctx.get("buyBelow"),
            sell_above=ctx.get("sellAbove"),
            current_price=ctx.get("currentPrice"),
        )
        fit = self._score_portfolio_fit(
            action=action,
            holding=holding,
            buy_below=ctx.get("buyBelow"),
            sell_above=ctx.get("sellAbove"),
            current_price=ctx.get("currentPrice"),
        )
        vetoes = self._vetoes(
            action=action,
            action_source=action_source,
            holding=holding,
            sell_above=ctx.get("sellAbove"),
            buy_below=ctx.get("buyBelow"),
            current_price=ctx.get("currentPrice"),
        )
        stability = self._stability(action=action, previous_actions=previous_actions or [])

        total = state["score"] + trigger["score"] + fit["score"]
        return {
            "schemaVersion": SCHEMA_VERSION,
            "symbol": symbol.upper(),
            "action": str(action or "hold").lower(),
            "confidence": str(confidence or "medium").lower(),
            "authority": "assessment",
            "scores": {
                "state": state["score"],
                "trigger": trigger["score"],
                "portfolioFit": fit["score"],
                "total": total,
            },
            "components": {
                "state": state,
                "trigger": trigger,
                "portfolioFit": fit,
            },
            "vetoes": vetoes,
            "stability": stability,
            "fitExtensions": {key: None for key in FIT_EXTENSION_KEYS},
            "rationale": rationale or "",
            "actionSource": action_source,
            "computedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
                "+00:00", "Z"
            ),
        }

    def build_from_assessment(
        self,
        assessment: dict[str, Any],
        *,
        context: dict[str, Any] | None = None,
        previous_actions: list[str] | None = None,
        news_sentiment: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Rebuild or refresh a proposal from a saved assessment row/payload."""
        ctx = context if context is not None else assessment.get("context")
        return self.build(
            symbol=assessment.get("symbol") or (ctx or {}).get("symbol") or "",
            action=assessment.get("action") or "hold",
            confidence=assessment.get("confidence") or "medium",
            rationale=assessment.get("rationale") or "",
            factors=assessment.get("factors") or [],
            action_source=assessment.get("actionSource"),
            context=ctx,
            previous_actions=previous_actions,
            news_sentiment=news_sentiment,
        )

    # --- pillar scorers -------------------------------------------------

    def _score_state(
        self,
        *,
        action: str,
        confidence: str,
        screening: dict[str, Any],
        fundamentals: dict[str, Any],
        note_factors: list[str],
        upside_pct: float | None,
        target_price: float | None,
        analyst_target: float | None,
        current_price: float | None,
    ) -> dict[str, Any]:
        score = 8.0  # base presence
        factors: list[str] = []

        upside = upside_pct
        if upside is None and current_price and (analyst_target or target_price):
            tgt = analyst_target or target_price
            if current_price > 0 and tgt:
                upside = (tgt - current_price) / current_price * 100
        if isinstance(upside, (int, float)):
            upside_pts = _clamp(float(upside) / 50.0 * 18.0, 0, 18)
            score += upside_pts
            factors.append(f"Upside vs target ≈ {float(upside):.1f}% → state +{upside_pts:.0f}")

        raw_screen = screening.get("score")
        if isinstance(raw_screen, (int, float)):
            screen_pts = _clamp(float(raw_screen) / 100.0 * 12.0, 0, 12)
            score += screen_pts
            factors.append(f"Screen score {raw_screen} → state +{screen_pts:.0f}")

        conf = (confidence or "").lower()
        conf_pts = {"high": 8.0, "medium": 4.0, "low": 1.0}.get(conf, 3.0)
        score += conf_pts
        factors.append(f"Assessment confidence {conf or 'n/a'} → state +{conf_pts:.0f}")

        # Light fundamentals health (optional enrichment keys vary by provider).
        op_margin = fundamentals.get("operatingMargins") or fundamentals.get("operatingMargin")
        rev_growth = fundamentals.get("revenueGrowth")
        if isinstance(op_margin, (int, float)) and op_margin > 0:
            score += 4
            factors.append("Positive operating margin → state +4")
        if isinstance(rev_growth, (int, float)) and rev_growth > 0.05:
            score += 4
            factors.append("Revenue growth supportive → state +4")

        note_hits = [
            f
            for f in note_factors
            if f.lower().startswith("your notes") or "growth trajectory" in f.lower()
        ]
        if note_hits:
            score += 4
            factors.append("Personal note thesis present → state +4")

        # Mild action alignment (scaffold only).
        if action in ("buy", "watch"):
            score += 2
        elif action == "sell":
            score = max(0, score - 4)
            factors.append("Sell action softens state score")

        capped = _round_score(_clamp(score, 0, STATE_MAX))
        return {"score": capped, "max": STATE_MAX, "factors": factors[:6]}

    def _score_trigger(
        self,
        *,
        action: str,
        action_source: str | None,
        alerts: list[dict[str, Any]],
        screening: dict[str, Any],
        technical: dict[str, Any] | None,
        news_sentiment: dict[str, Any] | None,
        buy_below: float | None,
        sell_above: float | None,
        current_price: float | None,
    ) -> dict[str, Any]:
        score = 0.0
        factors: list[str] = []

        src = (action_source or "").lower()
        if src == "rule_hard_trigger":
            score += 12
            factors.append("Hard personal threshold trigger → trigger +12")

        alert_n = len(alerts or [])
        if alert_n:
            alert_pts = min(alert_n * 4, 10)
            score += alert_pts
            factors.append(f"{alert_n} active alert(s) → trigger +{alert_pts}")

        flags = set(screening.get("flags") or [])
        if "fib_near" in flags or (
            isinstance(screening.get("fibDistancePct"), (int, float))
            and float(screening["fibDistancePct"]) <= 1.5
        ):
            score += 6
            factors.append("Price near Fibonacci level → trigger +6")
        if "below_buy" in flags or (
            buy_below is not None
            and current_price is not None
            and current_price <= buy_below
        ):
            score += 5
            factors.append("At/below buy-below threshold → trigger +5")
        if "above_sell" in flags or (
            sell_above is not None
            and current_price is not None
            and current_price >= sell_above
        ):
            score += 5
            factors.append("At/above sell-above threshold → trigger +5")

        stance = None
        if technical and isinstance(technical, dict):
            stance = technical.get("stance") or technical.get("overallStance")
        if not stance:
            stance = screening.get("techStance")
        if stance:
            stance_l = str(stance).lower()
            if any(k in stance_l for k in ("bull", "buy", "supportive")) and action in (
                "buy",
                "watch",
            ):
                score += 4
                factors.append(f"Technical stance {stance} aligns → trigger +4")
            elif any(k in stance_l for k in ("bear", "sell", "resist")) and action == "sell":
                score += 4
                factors.append(f"Technical stance {stance} aligns → trigger +4")
            else:
                factors.append(f"Technical stance: {stance}")

        if news_sentiment and news_sentiment.get("count"):
            sent = str(news_sentiment.get("sentiment") or "neutral").lower()
            if sent == "bullish" and action in ("buy", "watch"):
                score += 3
                factors.append("News sentiment bullish → trigger +3")
            elif sent == "bearish" and action == "sell":
                score += 3
                factors.append("News sentiment bearish → trigger +3")
            elif sent != "neutral":
                score += 1
                factors.append(f"News sentiment {sent} → trigger +1")

        if score == 0:
            factors.append("No active timing triggers")

        capped = _round_score(_clamp(score, 0, TRIGGER_MAX))
        return {"score": capped, "max": TRIGGER_MAX, "factors": factors[:6]}

    def _score_portfolio_fit(
        self,
        *,
        action: str,
        holding: dict[str, Any] | None,
        buy_below: float | None,
        sell_above: float | None,
        current_price: float | None,
    ) -> dict[str, Any]:
        score = 8.0  # neutral mid-band for watchlist / unknown
        factors: list[str] = []

        if not holding or not holding.get("quantity"):
            if action in ("buy", "watch"):
                score = 12
                factors.append("Not held — room to initiate → fit +12 base")
            elif action == "sell":
                score = 4
                factors.append("Sell on non-holding is weak fit")
            else:
                factors.append("Watchlist name — neutral portfolio fit")
            capped = _round_score(_clamp(score, 0, FIT_MAX))
            return {"score": capped, "max": FIT_MAX, "factors": factors[:6]}

        weight = holding.get("weightPct")
        if isinstance(weight, (int, float)):
            if weight < 10:
                score = 14
                factors.append(f"Weight {weight:.1f}% — room to add → fit strong")
            elif weight < CONCENTRATION_WARN_PCT:
                score = 11
                factors.append(f"Weight {weight:.1f}% — moderate → fit ok")
            elif weight < CONCENTRATION_VETO_PCT:
                score = 6
                factors.append(f"Weight {weight:.1f}% — concentrated → fit soft")
            else:
                score = 2
                factors.append(f"Weight {weight:.1f}% — very concentrated → fit weak")

        gain_pct = holding.get("gainPct")
        if isinstance(gain_pct, (int, float)):
            if gain_pct >= 50 and action in ("sell", "hold"):
                score += 2
                factors.append(
                    f"Large unrealized gain ({gain_pct:.0f}%) — tax-aware trim/hold context"
                )
            elif gain_pct <= -20 and action in ("buy", "watch"):
                score += 1
                factors.append(
                    f"Unrealized loss ({gain_pct:.0f}%) — harvest / average-down awareness"
                )

        if current_price is not None:
            if buy_below is not None and current_price <= buy_below * 1.02:
                score += 2
                factors.append("Near personal buy threshold — fit supports add")
            if sell_above is not None and current_price >= sell_above * 0.98:
                score += 2
                factors.append("Near personal sell threshold — fit supports trim")

        annual_div = holding.get("annualDividend")
        if isinstance(annual_div, (int, float)) and annual_div > 0:
            factors.append(
                f"Est. annual dividend ${annual_div:.2f}/sh (income target scoring TBD)"
            )

        capped = _round_score(_clamp(score, 0, FIT_MAX))
        return {"score": capped, "max": FIT_MAX, "factors": factors[:6]}

    def _vetoes(
        self,
        *,
        action: str,
        action_source: str | None,
        holding: dict[str, Any] | None,
        sell_above: float | None,
        buy_below: float | None,
        current_price: float | None,
    ) -> list[dict[str, str]]:
        vetoes: list[dict[str, str]] = []
        if (action_source or "").lower() == "rule_hard_trigger":
            vetoes.append(
                {
                    "code": "hard_threshold",
                    "message": "Personal threshold hard-trigger overrides discretionary scores",
                    "severity": "info",
                }
            )
        weight = holding.get("weightPct") if holding else None
        if isinstance(weight, (int, float)) and weight >= CONCENTRATION_VETO_PCT:
            vetoes.append(
                {
                    "code": "concentration",
                    "message": f"Position is {weight:.1f}% of portfolio (≥ {CONCENTRATION_VETO_PCT:.0f}%)",
                    "severity": "warn",
                }
            )
        if (
            action == "buy"
            and sell_above is not None
            and current_price is not None
            and current_price >= sell_above
        ):
            vetoes.append(
                {
                    "code": "sell_threshold_blocks_buy",
                    "message": "Price at/above sell-above while action is buy",
                    "severity": "block",
                }
            )
        if (
            action == "sell"
            and buy_below is not None
            and current_price is not None
            and current_price <= buy_below
            and (not holding or not holding.get("quantity"))
        ):
            vetoes.append(
                {
                    "code": "buy_zone_no_position",
                    "message": "In buy zone with no position — sell is inconsistent",
                    "severity": "warn",
                }
            )
        return vetoes

    def _stability(
        self, *, action: str, previous_actions: list[str]
    ) -> dict[str, Any]:
        """previous_actions: newest-first history *before* the current action."""
        action = str(action or "hold").lower()
        streak = 1
        for prev in previous_actions:
            if str(prev or "").lower() == action:
                streak += 1
            else:
                break
        flipped = bool(previous_actions) and str(previous_actions[0] or "").lower() != action
        hysteresis_hint = None
        if flipped:
            hysteresis_hint = (
                f"Action changed from {previous_actions[0]} → {action}; "
                "prefer confirmation before acting"
            )
        return {
            "sameActionStreak": streak,
            "confirmationRequired": CONFIRMATION_REQUIRED,
            "confirmed": streak >= CONFIRMATION_REQUIRED,
            "hysteresisHint": hysteresis_hint,
            "cooldownUntil": None,
        }
