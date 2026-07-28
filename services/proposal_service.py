"""Trading proposal — State / Trigger / Portfolio Fit.

Slice 1: schema + heuristic scores (assessment action remains authoritative).
Slice 2: track-record-informed weight scales + optional PROPOSAL_STABILITY_GATE.
Slice 3: Portfolio Fit preferences (dividend / volatility / concentration).

See docs/PROPOSAL_FRAMEWORK.md.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = 1
STATE_MAX = 50
TRIGGER_MAX = 30
FIT_MAX = 20

# Soft defaults when the user has not set maxSingleNameWeightPct.
CONCENTRATION_WARN_PCT = 20.0
CONCENTRATION_VETO_PCT = 40.0

CONFIRMATION_REQUIRED = 2

# Slice 2: when on, unconfirmed action flips publish the prior action on proposal.action
# (assessment / SAI action is unchanged). Default off for A/B.
PROPOSAL_STABILITY_GATE = os.environ.get("PROPOSAL_STABILITY_GATE", "0").lower() not in (
    "0",
    "false",
    "no",
    "off",
)

# Soft-nudge State/Trigger sub-weights from Agent Signal Record when enough samples exist.
PROPOSAL_TRACK_RECORD_WEIGHTS = os.environ.get(
    "PROPOSAL_TRACK_RECORD_WEIGHTS", "1"
).lower() not in ("0", "false", "no", "off")
TRACK_RECORD_WEIGHT_MIN_N = 8

FIT_EXTENSION_KEYS = (
    "targetAnnualDividend",
    "volatilityPreference",
    "maxSingleNameWeightPct",
    "sectorCapPct",
    "taxLotPreference",
    "filterSetBias",
)

# volatilityPreference → soft beta ceiling (fundamentals.beta when present).
VOLATILITY_BETA_CEILING = {
    "low": 1.0,
    "moderate": 1.4,
    "high": 2.5,
}


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _round_score(value: float) -> int:
    return int(round(_clamp(value, 0, 100)))


def pillar_scales_from_track_record(summary: dict[str, Any] | None) -> dict[str, float]:
    """Map Agent Signal Record hit rates → State/Trigger soft multipliers.

    recommendation hit-rate nudges State; pattern/confluence nudge Trigger.
    Returns scales near 1.0 when data is thin.
    """
    scales = {"state": 1.0, "trigger": 1.0}
    if not summary:
        return scales
    by_kind = summary.get("byKind") or {}
    rec = by_kind.get("recommendation") or {}
    pattern = by_kind.get("pattern") or {}
    confluence = by_kind.get("confluence") or {}

    def _hit(bucket: dict[str, Any]) -> tuple[float | None, int]:
        n = int(bucket.get("wins", 0) or 0) + int(bucket.get("losses", 0) or 0)
        rate = bucket.get("hitRate")
        if rate is None or n < TRACK_RECORD_WEIGHT_MIN_N:
            return None, n
        return float(rate), n

    rec_hit, _ = _hit(rec)
    if rec_hit is not None:
        # 50% → 1.0, 70% → ~1.12, 30% → ~0.88
        scales["state"] = _clamp(0.85 + (rec_hit - 0.5) * 0.6, 0.85, 1.15)

    pat_hit, _ = _hit(pattern)
    conf_hit, _ = _hit(confluence)
    trigger_hits = [h for h in (pat_hit, conf_hit) if h is not None]
    if trigger_hits:
        avg = sum(trigger_hits) / len(trigger_hits)
        scales["trigger"] = _clamp(0.85 + (avg - 0.5) * 0.7, 0.85, 1.18)
    return scales


def _fund_get(fundamentals: dict[str, Any], *keys: str) -> Any:
    """Read a fundamentals field from flat or nested enrichment shapes."""
    if not fundamentals:
        return None
    for key in keys:
        if key in fundamentals and fundamentals[key] is not None:
            return fundamentals[key]
    for group in (
        "profile",
        "growthProfitability",
        "valuation",
        "financialHealth",
        "analyst",
    ):
        block = fundamentals.get(group)
        if isinstance(block, dict):
            for key in keys:
                if key in block and block[key] is not None:
                    return block[key]
    return None


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
        fit_prefs: dict[str, Any] | None = None,
        track_record_summary: dict[str, Any] | None = None,
        portfolio_annual_dividend: float | None = None,
    ) -> dict[str, Any]:
        ctx = context or {}
        screening = screening if screening is not None else (ctx.get("screening") or {})
        holding = holding if holding is not None else ctx.get("holding")
        alerts = alerts if alerts is not None else (ctx.get("alerts") or [])
        technical = technical if technical is not None else ctx.get("technical")
        factors = [str(f) for f in (factors or [])]
        prefs = self._normalize_fit_prefs(fit_prefs or ctx.get("fitPrefs"))
        if portfolio_annual_dividend is None:
            portfolio_annual_dividend = ctx.get("portfolioAnnualDividend")

        scales = {"state": 1.0, "trigger": 1.0}
        if PROPOSAL_TRACK_RECORD_WEIGHTS:
            scales = pillar_scales_from_track_record(track_record_summary)

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
            scale=scales["state"],
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
            scale=scales["trigger"],
        )
        fit = self._score_portfolio_fit(
            action=action,
            holding=holding,
            buy_below=ctx.get("buyBelow"),
            sell_above=ctx.get("sellAbove"),
            current_price=ctx.get("currentPrice"),
            fit_prefs=prefs,
            fundamentals=ctx.get("fundamentals") or {},
            portfolio_annual_dividend=portfolio_annual_dividend,
        )
        vetoes = self._vetoes(
            action=action,
            action_source=action_source,
            holding=holding,
            sell_above=ctx.get("sellAbove"),
            buy_below=ctx.get("buyBelow"),
            current_price=ctx.get("currentPrice"),
            fit_prefs=prefs,
            fundamentals=ctx.get("fundamentals") or {},
        )
        stability = self._stability(action=action, previous_actions=previous_actions or [])

        published_action = str(action or "hold").lower()
        if (
            PROPOSAL_STABILITY_GATE
            and not stability["confirmed"]
            and previous_actions
            and str(previous_actions[0] or "").lower() != published_action
        ):
            published_action = str(previous_actions[0]).lower()
            stability["gated"] = True
            stability["rawAction"] = str(action or "hold").lower()
            stability["hysteresisHint"] = (
                f"Stability gate held {published_action} "
                f"(unconfirmed flip from assessment {stability['rawAction']})"
            )
        else:
            stability["gated"] = False
            stability["rawAction"] = published_action

        total = state["score"] + trigger["score"] + fit["score"]
        fit_extensions = {key: None for key in FIT_EXTENSION_KEYS}
        for key in FIT_EXTENSION_KEYS:
            if key in prefs and prefs[key] is not None:
                fit_extensions[key] = prefs[key]

        return {
            "schemaVersion": SCHEMA_VERSION,
            "symbol": symbol.upper(),
            "action": published_action,
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
            "fitExtensions": fit_extensions,
            "weightScales": {
                "state": round(scales["state"], 3),
                "trigger": round(scales["trigger"], 3),
                "fromTrackRecord": bool(
                    PROPOSAL_TRACK_RECORD_WEIGHTS and track_record_summary
                ),
            },
            "rationale": rationale or "",
            "actionSource": action_source,
            "computedAt": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
        }

    def build_from_assessment(
        self,
        assessment: dict[str, Any],
        *,
        context: dict[str, Any] | None = None,
        previous_actions: list[str] | None = None,
        news_sentiment: dict[str, Any] | None = None,
        fit_prefs: dict[str, Any] | None = None,
        track_record_summary: dict[str, Any] | None = None,
        portfolio_annual_dividend: float | None = None,
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
            fit_prefs=fit_prefs,
            track_record_summary=track_record_summary,
            portfolio_annual_dividend=portfolio_annual_dividend,
        )

    @staticmethod
    def _normalize_fit_prefs(raw: dict[str, Any] | None) -> dict[str, Any]:
        raw = raw or {}
        # Accept either flat keys or nested under portfolioFit.
        nested = raw.get("portfolioFit") if isinstance(raw.get("portfolioFit"), dict) else None
        src = nested or raw
        out: dict[str, Any] = {}
        tad = src.get("targetAnnualDividend")
        if isinstance(tad, (int, float)) and tad >= 0:
            out["targetAnnualDividend"] = float(tad)
        vol = src.get("volatilityPreference")
        if isinstance(vol, str) and vol.strip().lower() in VOLATILITY_BETA_CEILING:
            out["volatilityPreference"] = vol.strip().lower()
        cap = src.get("maxSingleNameWeightPct")
        if isinstance(cap, (int, float)) and 0 < float(cap) <= 100:
            out["maxSingleNameWeightPct"] = float(cap)
        for key in ("sectorCapPct", "taxLotPreference", "filterSetBias"):
            if src.get(key) is not None:
                out[key] = src[key]
        return out

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
        scale: float = 1.0,
    ) -> dict[str, Any]:
        # Slice 2 baseline: slightly less raw-confidence weight, more thesis/upside.
        score = 6.0
        factors: list[str] = []

        upside = upside_pct
        if upside is None and current_price and (analyst_target or target_price):
            tgt = analyst_target or target_price
            if current_price > 0 and tgt:
                upside = (tgt - current_price) / current_price * 100
        if isinstance(upside, (int, float)):
            upside_pts = _clamp(float(upside) / 45.0 * 20.0, 0, 20)
            score += upside_pts
            factors.append(f"Upside vs target ≈ {float(upside):.1f}% → state +{upside_pts:.0f}")

        raw_screen = screening.get("score")
        if isinstance(raw_screen, (int, float)):
            screen_pts = _clamp(float(raw_screen) / 100.0 * 10.0, 0, 10)
            score += screen_pts
            factors.append(f"Screen score {raw_screen} → state +{screen_pts:.0f}")

        conf = (confidence or "").lower()
        conf_pts = {"high": 7.0, "medium": 3.5, "low": 0.5}.get(conf, 2.5)
        score += conf_pts
        factors.append(f"Assessment confidence {conf or 'n/a'} → state +{conf_pts:.0f}")

        op_margin = _fund_get(fundamentals, "operatingMargins", "operatingMargin")
        rev_growth = _fund_get(fundamentals, "revenueGrowth")
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
            score += 6
            factors.append("Personal note thesis present → state +6")

        if action in ("buy", "watch"):
            score += 2
        elif action == "sell":
            score = max(0, score - 4)
            factors.append("Sell action softens state score")

        if scale != 1.0:
            score *= scale
            factors.append(f"Track-record state scale ×{scale:.2f}")

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
        scale: float = 1.0,
    ) -> dict[str, Any]:
        # Slice 2: slightly less alert spam, more Fib/stance/news alignment.
        score = 0.0
        factors: list[str] = []

        src = (action_source or "").lower()
        if src == "rule_hard_trigger":
            score += 10
            factors.append("Hard personal threshold trigger → trigger +10")

        alert_n = len(alerts or [])
        if alert_n:
            alert_pts = min(alert_n * 3, 8)
            score += alert_pts
            factors.append(f"{alert_n} active alert(s) → trigger +{alert_pts}")

        flags = set(screening.get("flags") or [])
        if "fib_near" in flags or (
            isinstance(screening.get("fibDistancePct"), (int, float))
            and float(screening["fibDistancePct"]) <= 1.5
        ):
            score += 8
            factors.append("Price near Fibonacci level → trigger +8")
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
                score += 5
                factors.append(f"Technical stance {stance} aligns → trigger +5")
            elif any(k in stance_l for k in ("bear", "sell", "resist")) and action == "sell":
                score += 5
                factors.append(f"Technical stance {stance} aligns → trigger +5")
            else:
                factors.append(f"Technical stance: {stance}")

        if news_sentiment and news_sentiment.get("count"):
            sent = str(news_sentiment.get("sentiment") or "neutral").lower()
            if sent == "bullish" and action in ("buy", "watch"):
                score += 4
                factors.append("News sentiment bullish → trigger +4")
            elif sent == "bearish" and action == "sell":
                score += 4
                factors.append("News sentiment bearish → trigger +4")
            elif sent != "neutral":
                score += 1
                factors.append(f"News sentiment {sent} → trigger +1")

        if score == 0:
            factors.append("No active timing triggers")

        if scale != 1.0:
            score *= scale
            factors.append(f"Track-record trigger scale ×{scale:.2f}")

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
        fit_prefs: dict[str, Any],
        fundamentals: dict[str, Any],
        portfolio_annual_dividend: float | None,
    ) -> dict[str, Any]:
        score = 8.0
        factors: list[str] = []
        warn_pct = float(fit_prefs.get("maxSingleNameWeightPct") or CONCENTRATION_WARN_PCT)
        veto_pct = max(warn_pct * 1.5, warn_pct + 5.0)
        if fit_prefs.get("maxSingleNameWeightPct") is None:
            veto_pct = CONCENTRATION_VETO_PCT

        if not holding or not holding.get("quantity"):
            if action in ("buy", "watch"):
                score = 12
                factors.append("Not held — room to initiate → fit +12 base")
            elif action == "sell":
                score = 4
                factors.append("Sell on non-holding is weak fit")
            else:
                factors.append("Watchlist name — neutral portfolio fit")
            score = self._apply_pref_fit_bonuses(
                score,
                factors,
                action=action,
                holding=None,
                fit_prefs=fit_prefs,
                fundamentals=fundamentals,
                portfolio_annual_dividend=portfolio_annual_dividend,
            )
            capped = _round_score(_clamp(score, 0, FIT_MAX))
            return {"score": capped, "max": FIT_MAX, "factors": factors[:6]}

        weight = holding.get("weightPct")
        if isinstance(weight, (int, float)):
            if weight < min(10.0, warn_pct * 0.5):
                score = 14
                factors.append(f"Weight {weight:.1f}% — room to add → fit strong")
            elif weight < warn_pct:
                score = 11
                factors.append(f"Weight {weight:.1f}% — under cap {warn_pct:.0f}% → fit ok")
            elif weight < veto_pct:
                score = 6
                factors.append(f"Weight {weight:.1f}% — near/over cap {warn_pct:.0f}% → fit soft")
            else:
                score = 2
                factors.append(f"Weight {weight:.1f}% — over hard band {veto_pct:.0f}% → fit weak")

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

        score = self._apply_pref_fit_bonuses(
            score,
            factors,
            action=action,
            holding=holding,
            fit_prefs=fit_prefs,
            fundamentals=fundamentals,
            portfolio_annual_dividend=portfolio_annual_dividend,
        )

        capped = _round_score(_clamp(score, 0, FIT_MAX))
        return {"score": capped, "max": FIT_MAX, "factors": factors[:6]}

    def _apply_pref_fit_bonuses(
        self,
        score: float,
        factors: list[str],
        *,
        action: str,
        holding: dict[str, Any] | None,
        fit_prefs: dict[str, Any],
        fundamentals: dict[str, Any],
        portfolio_annual_dividend: float | None,
    ) -> float:
        target_div = fit_prefs.get("targetAnnualDividend")
        if isinstance(target_div, (int, float)) and target_div > 0:
            portfolio_div = portfolio_annual_dividend
            if not isinstance(portfolio_div, (int, float)):
                portfolio_div = 0.0
            gap = float(target_div) - float(portfolio_div)
            name_div = None
            if holding:
                per_sh = holding.get("annualDividend")
                qty = holding.get("quantity") or 0
                if isinstance(per_sh, (int, float)) and qty:
                    name_div = float(per_sh) * float(qty)
            # Fundamentals dividendYield as fallback signal for watchlist adds.
            dy = _fund_get(fundamentals, "dividendYield")
            if name_div is None and isinstance(dy, (int, float)) and dy > 0:
                name_div = dy  # yield fraction used only as presence signal

            if gap > 0 and action in ("buy", "watch"):
                if isinstance(name_div, (int, float)) and name_div > 0:
                    score += 3
                    factors.append(
                        f"Income gap ${gap:,.0f} vs target — dividend name helps → fit +3"
                    )
                else:
                    score -= 1
                    factors.append("Income target set but name pays little/no dividend")
            elif gap <= 0:
                factors.append("Portfolio income at/above target annual dividend")

        vol = fit_prefs.get("volatilityPreference")
        if vol in VOLATILITY_BETA_CEILING:
            ceiling = VOLATILITY_BETA_CEILING[vol]
            beta = _fund_get(fundamentals, "beta")
            if isinstance(beta, (int, float)):
                if beta <= ceiling and action in ("buy", "watch", "hold"):
                    score += 2
                    factors.append(
                        f"Beta {beta:.2f} within {vol} ceiling {ceiling:.1f} → fit +2"
                    )
                elif beta > ceiling and action in ("buy", "watch"):
                    score -= 3
                    factors.append(
                        f"Beta {beta:.2f} above {vol} ceiling {ceiling:.1f} → fit −3"
                    )
            else:
                factors.append(f"Volatility preference {vol} (beta unavailable)")

        return score

    def _vetoes(
        self,
        *,
        action: str,
        action_source: str | None,
        holding: dict[str, Any] | None,
        sell_above: float | None,
        buy_below: float | None,
        current_price: float | None,
        fit_prefs: dict[str, Any],
        fundamentals: dict[str, Any],
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
        warn_pct = float(fit_prefs.get("maxSingleNameWeightPct") or CONCENTRATION_WARN_PCT)
        veto_pct = (
            max(warn_pct * 1.5, warn_pct + 5.0)
            if fit_prefs.get("maxSingleNameWeightPct") is not None
            else CONCENTRATION_VETO_PCT
        )
        weight = holding.get("weightPct") if holding else None
        if isinstance(weight, (int, float)) and weight >= veto_pct:
            vetoes.append(
                {
                    "code": "concentration",
                    "message": f"Position is {weight:.1f}% of portfolio (≥ {veto_pct:.0f}%)",
                    "severity": "warn",
                }
            )
        vol = fit_prefs.get("volatilityPreference")
        if vol in VOLATILITY_BETA_CEILING and action in ("buy", "watch"):
            beta = _fund_get(fundamentals, "beta")
            ceiling = VOLATILITY_BETA_CEILING[vol]
            if isinstance(beta, (int, float)) and beta > ceiling * 1.25:
                vetoes.append(
                    {
                        "code": "volatility_preference",
                        "message": (
                            f"Beta {beta:.2f} far above {vol} preference ceiling {ceiling:.1f}"
                        ),
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
