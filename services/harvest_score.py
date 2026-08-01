"""Tax-loss residual Loss-score and Winner Trim Score (server mirror of dashboard).

Used by Portfolio Fit nudges and harvest alert evaluation. Scores are mark-to-market
signals; cash sizing stays client/Simulation-side.
"""

from __future__ import annotations

from typing import Any

# Loss-score curve (matches dashboard TAX_PROPOSAL_LOSS_SCORE_*)
LOSS_SCORE_WEIGHT = 50.0
LOSS_SCORE_AT_GATE = 30.0
LOSS_SCORE_ANCHOR_PCT = 50.0

# Trim-score caps (matches dashboard)
TRIM_HEADROOM_REF_PCT = 60.0
TRIM_WEIGHT_REF_PCT = 10.0
TRIM_PEAK_FLOOR_PCT = 80.0

# Alert / Fit thresholds
LOSS_SCORE_ALERT_MIN = 25.0
TRIM_SCORE_ALERT_MIN = 35.0
FIT_HARVEST_NUDGE_CAP = 3.0


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _clamp01(value: float) -> float:
    return _clamp(value, 0.0, 1.0)


def residual_loss_pct(gain_pct: float | None, analyst_upside_pct: float | None) -> float | None:
    """Expected residual %-loss vs cost after 1YT. Missing 1YT → U=0."""
    if gain_pct is None or not isinstance(gain_pct, (int, float)) or gain_pct >= 0:
        return None
    loss_pct = abs(float(gain_pct))
    if loss_pct <= 0:
        return None
    L = min(1.0, loss_pct / 100.0)
    U = float(analyst_upside_pct) / 100.0 if isinstance(analyst_upside_pct, (int, float)) else 0.0
    return max(0.0, 100.0 * (1.0 - (1.0 - L) * (1.0 + U)))


def loss_score_from_residual(residual_pct: float | None) -> float:
    if residual_pct is None or residual_pct <= 0:
        return 0.0
    gate = LOSS_SCORE_ANCHOR_PCT
    floor_pts = LOSS_SCORE_AT_GATE
    max_pts = LOSS_SCORE_WEIGHT
    if residual_pct <= gate:
        return (residual_pct / gate) * floor_pts
    t = min(1.0, (residual_pct - gate) / (100.0 - gate))
    return floor_pts + t * (max_pts - floor_pts)


def loss_score(gain_pct: float | None, analyst_upside_pct: float | None) -> float:
    return loss_score_from_residual(residual_loss_pct(gain_pct, analyst_upside_pct))


def trim_headroom_pct(
    analyst_upside_pct: float | None,
    personal_upside_pct: float | None,
) -> float:
    u1yt = max(0.0, float(analyst_upside_pct)) if isinstance(analyst_upside_pct, (int, float)) else 0.0
    if isinstance(personal_upside_pct, (int, float)):
        u_pt = max(0.0, float(personal_upside_pct))
    else:
        u_pt = u1yt
    return 0.4 * u1yt + 0.6 * u_pt


def trim_score(
    *,
    analyst_upside_pct: float | None,
    personal_upside_pct: float | None,
    peak_pct: float | None,
    weight_pct: float | None,
    buy_qty: float = 0.0,
    sell_qty: float = 0.0,
    held: float = 0.0,
) -> dict[str, float]:
    headroom = trim_headroom_pct(analyst_upside_pct, personal_upside_pct)
    exhaust_pts = 30.0 * _clamp01(1.0 - headroom / TRIM_HEADROOM_REF_PCT)
    if peak_pct is None or not isinstance(peak_pct, (int, float)):
        peak_pts = 10.0
    else:
        peak_pts = 20.0 * _clamp01(
            (float(peak_pct) - TRIM_PEAK_FLOOR_PCT) / (100.0 - TRIM_PEAK_FLOOR_PCT)
        )
    if weight_pct is None or not isinstance(weight_pct, (int, float)) or weight_pct <= 0:
        weight_pts = 0.0
    else:
        weight_pts = 15.0 * _clamp01(float(weight_pct) / TRIM_WEIGHT_REF_PCT)

    buy = max(0.0, float(buy_qty or 0.0))
    sell = max(0.0, float(sell_qty or 0.0))
    held_qty = max(0.0, float(held or 0.0))
    net = buy - sell
    denom = max(held_qty, buy + sell, 1.0)
    if net > 0:
        intent_pts = -10.0 * _clamp01(net / denom)
    elif net < 0:
        intent_pts = 10.0 * _clamp01(abs(net) / denom)
    elif sell > 0:
        intent_pts = 5.0
    else:
        intent_pts = 0.0

    score = max(0.0, exhaust_pts + peak_pts + weight_pts + intent_pts)
    return {
        "headroomPct": headroom,
        "exhaustPts": exhaust_pts,
        "peakPts": peak_pts,
        "weightPts": weight_pts,
        "intentPts": intent_pts,
        "trimScore": score,
    }


def fit_harvest_nudge(
    *,
    action: str,
    gain_pct: float | None,
    analyst_upside_pct: float | None,
    personal_upside_pct: float | None,
    peak_pct: float | None = None,
    weight_pct: float | None = None,
    buy_qty: float = 0.0,
    sell_qty: float = 0.0,
    held: float = 0.0,
) -> tuple[float, list[str]]:
    """Soft Fit adjustment from harvest scores. Capped at ±FIT_HARVEST_NUDGE_CAP."""
    action = str(action or "hold").lower()
    factors: list[str] = []
    nudge = 0.0

    ls = loss_score(gain_pct, analyst_upside_pct)
    if ls >= LOSS_SCORE_ALERT_MIN:
        if action in ("sell", "watch"):
            delta = 2.0 if ls >= 35 else 1.0
            nudge += delta
            factors.append(f"High residual loss-score ({ls:.0f}) — harvest fit +{delta:.0f}")
        elif action == "buy":
            nudge -= 1.0
            factors.append(f"High residual loss-score ({ls:.0f}) — weak add fit −1")

    ts = trim_score(
        analyst_upside_pct=analyst_upside_pct,
        personal_upside_pct=personal_upside_pct,
        peak_pct=peak_pct,
        weight_pct=weight_pct,
        buy_qty=buy_qty,
        sell_qty=sell_qty,
        held=held,
    )["trimScore"]
    if ts >= TRIM_SCORE_ALERT_MIN:
        if action in ("sell", "watch"):
            delta = 2.0 if ts >= 45 else 1.0
            nudge += delta
            factors.append(f"High trim-score ({ts:.0f}) — trim-friendly fit +{delta:.0f}")
        elif action in ("buy",):
            nudge -= 1.0
            factors.append(f"High trim-score ({ts:.0f}) — protect winner −1")

    nudge = _clamp(nudge, -FIT_HARVEST_NUDGE_CAP, FIT_HARVEST_NUDGE_CAP)
    return nudge, factors


def upside_pct(target: float | None, price: float | None) -> float | None:
    if (
        isinstance(target, (int, float))
        and isinstance(price, (int, float))
        and price > 0
    ):
        return (float(target) - float(price)) / float(price) * 100.0
    return None


def peak_proximity_pct(price: float | None, high_52w: float | None) -> float | None:
    if (
        isinstance(price, (int, float))
        and isinstance(high_52w, (int, float))
        and high_52w > 0
    ):
        return float(price) / float(high_52w) * 100.0
    return None


def scores_for_holding_context(ctx: dict[str, Any]) -> dict[str, Any]:
    """Compute both scores from a loose context dict (assessment / alerts)."""
    holding = ctx.get("holding") or {}
    price = ctx.get("currentPrice") or holding.get("currentPrice")
    gain_pct = holding.get("gainPct")
    analyst = ctx.get("analystTarget1y") or holding.get("analystTarget1y")
    personal = (
        ctx.get("personalTarget")
        or holding.get("personalTarget")
        or ctx.get("targetPrice")
        or holding.get("targetPrice")
    )
    a_up = upside_pct(analyst, price) if analyst else holding.get("analystUpsidePct")
    p_up = upside_pct(personal, price) if personal else holding.get("personalUpsidePct")
    peak = peak_proximity_pct(price, ctx.get("high52w"))
    weight = holding.get("weightPct")
    buy_qty = float(ctx.get("buyPlanQty") or 0)
    sell_qty = float(ctx.get("sellPlanQty") or 0)
    held = float(holding.get("quantity") or 0)
    ls = loss_score(gain_pct if isinstance(gain_pct, (int, float)) else None, a_up)
    ts = trim_score(
        analyst_upside_pct=a_up,
        personal_upside_pct=p_up,
        peak_pct=peak,
        weight_pct=weight if isinstance(weight, (int, float)) else None,
        buy_qty=buy_qty,
        sell_qty=sell_qty,
        held=held,
    )
    return {
        "lossScore": ls,
        "trimScore": ts["trimScore"],
        "residualLossPct": residual_loss_pct(
            gain_pct if isinstance(gain_pct, (int, float)) else None, a_up
        ),
        "analystUpsidePct": a_up,
        "personalUpsidePct": p_up,
        "peakPct": peak,
        **ts,
    }
