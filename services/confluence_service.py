"""Confluence agent — fuse the independent technical reads into one verdict (Phase 3).

The earlier agents each look at the tape through a single lens:

* **Trend** — moving-average stack, golden/death cross, 3-month slope.
* **Structure** — the adaptive zig-zag's higher-highs/lower-lows read.
* **Momentum** — MACD histogram / RSI regime.
* **Pattern** (+ Risk) — named chart patterns, already volume-validated by the
  Risk agent (confirmed / weak / pending / veto / stale).
* **Volume** — relative volume regime and OBV accumulation/distribution.

On their own any one of them can mislead. The Confluence agent casts each as a
*weighted directional vote*, then aggregates them into a single bias
(Bullish … Bearish), a normalised score, and — crucially — an explicit list of
**agreements** and **conflicts** so the recommendation (and the LLM in Phase 4)
can reason "trend, structure and a confirmed pattern all point up; only light
volume dissents" instead of trusting one signal blindly.

Pure function: ``compute_confluence(signals)`` takes the dict produced by
``TechnicalSignalsService.compute_signals`` (or an equivalent assembled in the
chart path) and returns a confluence block, or ``None`` when there isn't enough
to fuse. No network, no mutation — unit-testable in isolation.
"""
from __future__ import annotations

import os
from typing import Any

from services.volume_service import OBV_FLAT_BAND

# Per-agent base weights (how much each lens counts before magnitude scaling).
# Env-tunable, same convention as the rest of the technical stack.
W_TREND = float(os.environ.get("CONFLUENCE_WEIGHT_TREND", "1.0"))
W_STRUCTURE = float(os.environ.get("CONFLUENCE_WEIGHT_STRUCTURE", "0.8"))
W_MOMENTUM = float(os.environ.get("CONFLUENCE_WEIGHT_MOMENTUM", "0.5"))
W_PATTERN = float(os.environ.get("CONFLUENCE_WEIGHT_PATTERN", "1.0"))
W_VOLUME = float(os.environ.get("CONFLUENCE_WEIGHT_VOLUME", "0.6"))

# Score band edges (on the -1..+1 net axis) for the bias label.
_LEAN_AT = float(os.environ.get("CONFLUENCE_LEAN_SCORE", "0.15"))
_STRONG_AT = float(os.environ.get("CONFLUENCE_STRONG_SCORE", "0.45"))

# RVOL the Risk agent wants on a breakout — mirrored here only for phrasing the
# "what would confirm this pattern" watch precondition (kept in sync via the same
# env var so the wording can't drift from the actual gate).
BREAKOUT_RVOL_HINT = float(os.environ.get("VOLUME_BREAKOUT_RVOL", "1.3"))

# How much a Risk-agent verdict scales a pattern's vote weight.
_VERDICT_FACTOR = {
    "confirmed": 1.0,
    "weak": 0.6,
    "pending": 0.45,
    "veto": 0.1,
    "stale": 0.05,
}

_EPS = 1e-9


def _sign_word(value: float) -> str:
    if value > 0:
        return "bull"
    if value < 0:
        return "bear"
    return "neutral"


def _vote(
    agent: str,
    direction: int,
    weight: float,
    label: str,
    detail: str | None = None,
) -> dict[str, Any]:
    return {
        "agent": agent,
        "direction": _sign_word(direction),
        "sign": int(direction),
        "weight": round(max(0.0, weight), 3),
        "label": label,
        "detail": detail,
    }


def _trend_vote(trend: dict[str, Any] | None) -> dict[str, Any] | None:
    if not trend:
        return None
    ma = trend.get("maStack")
    slope = trend.get("slopePctPerYr")
    cross = trend.get("crossState")

    direction = 0
    mag = 0.3
    if ma == "bullish":
        direction, mag = 1, 0.9
    elif ma == "bearish":
        direction, mag = -1, 0.9
    elif isinstance(slope, (int, float)):
        if slope > 10:
            direction, mag = 1, 0.45
        elif slope < -10:
            direction, mag = -1, 0.45

    # A fresh cross reinforces a matching bias.
    if direction > 0 and cross == "golden":
        mag = min(1.0, mag + 0.1)
    elif direction < 0 and cross == "death":
        mag = min(1.0, mag + 0.1)

    stack_word = {"bullish": "bullish", "bearish": "bearish", "mixed": "mixed"}.get(ma, "mixed")
    slope_txt = f", {slope:+.0f}%/yr" if isinstance(slope, (int, float)) else ""
    label = f"Trend: MA stack {stack_word}{slope_txt}"
    detail = f"50/200 cross {cross}" if cross else None
    return _vote("trend", direction, W_TREND * mag, label, detail)


def _structure_vote(swing: dict[str, Any] | None) -> dict[str, Any] | None:
    if not swing:
        return None
    structure = str(swing.get("structure") or "").lower()
    direction = 0
    mag = 0.3
    if "uptrend" in structure:
        direction, mag = 1, 0.9
    elif "downtrend" in structure:
        direction, mag = -1, 0.9
    elif "rising lows" in structure:
        direction, mag = 1, 0.5
    elif "falling highs" in structure:
        direction, mag = -1, 0.5
    label = f"Structure: {swing.get('structure') or 'range / mixed'}"
    return _vote("structure", direction, W_STRUCTURE * mag, label)


def _momentum_vote(momentum: dict[str, Any] | None) -> dict[str, Any] | None:
    if not momentum:
        return None
    macd = momentum.get("macd") or {}
    rsi = momentum.get("rsi14")
    zone = momentum.get("rsiZone")

    direction = 0
    mag = 0.4
    state = macd.get("state")
    if state == "bullish":
        direction, mag = 1, 0.6
    elif state == "bearish":
        direction, mag = -1, 0.6
    elif isinstance(rsi, (int, float)):
        if rsi >= 55:
            direction, mag = 1, 0.4
        elif rsi <= 45:
            direction, mag = -1, 0.4

    rsi_txt = f"RSI {rsi:.0f}" if isinstance(rsi, (int, float)) else "RSI —"
    macd_txt = f"MACD {state}" if state else "MACD —"
    detail = f"{zone} zone" if zone and zone != "neutral" else None
    return _vote("momentum", direction, W_MOMENTUM * mag, f"Momentum: {macd_txt}, {rsi_txt}", detail)


def _pattern_vote(patterns: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    if not patterns:
        return None
    net = 0.0
    weight_sum = 0.0
    lead_name = None
    lead_w = 0.0
    lead_verdict = None
    for p in patterns:
        ptype = str(p.get("type") or "neutral").lower()
        direction = 1 if ptype == "bullish" else -1 if ptype == "bearish" else 0
        if direction == 0:
            continue
        validation = p.get("validation") or {}
        verdict = validation.get("verdict")
        factor = _VERDICT_FACTOR.get(verdict, 0.5)
        conf = validation.get("adjustedConfidence")
        if not isinstance(conf, (int, float)):
            conf = p.get("confidence") if isinstance(p.get("confidence"), (int, float)) else 0.5
        w = factor * float(conf)
        net += direction * w
        weight_sum += w
        if w > lead_w:
            lead_w, lead_name, lead_verdict = w, p.get("name"), verdict

    if weight_sum <= _EPS or lead_name is None:
        return None
    direction = 1 if net > 0 else -1 if net < 0 else 0
    # The pattern lens caps at its base weight; a single strong confirmed pattern
    # already saturates it, multiple aligned ones keep it pinned.
    weight = W_PATTERN * min(1.0, weight_sum)
    verdict_txt = f" ({lead_verdict})" if lead_verdict else ""
    label = f"Pattern: {lead_name}{verdict_txt}"
    return _vote("pattern", direction, weight, label)


def _volume_vote(
    volume: dict[str, Any] | None, profile: dict[str, Any] | None
) -> dict[str, Any] | None:
    if not volume:
        return None
    obv = volume.get("obvSlopePct")
    state = volume.get("state")
    rvol = volume.get("rvol")

    direction = 0
    if isinstance(obv, (int, float)):
        # Shared OBV neutral band (see volume_service.OBV_FLAT_BAND) so the lens and
        # the UI badge can't disagree on accumulation/distribution/flat.
        if obv > OBV_FLAT_BAND:
            direction = 1
        elif obv < -OBV_FLAT_BAND:
            direction = -1

    state_w = {"surging": 1.0, "elevated": 0.8, "normal": 0.5, "light": 0.3}.get(state, 0.5)
    weight = W_VOLUME * state_w

    rvol_txt = f"{rvol:.2f}× vol" if isinstance(rvol, (int, float)) else "vol —"
    flow = "accumulation" if direction > 0 else "distribution" if direction < 0 else "flat OBV"
    node = (profile or {}).get("priceNode") or {}
    node_kind = node.get("node")
    detail = None
    if node_kind == "low" or node_kind == "gap":
        detail = "price in a low-volume node (thin support)"
    elif node_kind == "high":
        detail = "price on a high-volume node (firm support/resistance)"
    return _vote("volume", direction, weight, f"Volume: {rvol_txt}, {flow}", detail)


def _bias_from_score(score: float) -> str:
    if score >= _STRONG_AT:
        return "Bullish"
    if score >= _LEAN_AT:
        return "Lean Bullish"
    if score <= -_STRONG_AT:
        return "Bearish"
    if score <= -_LEAN_AT:
        return "Lean Bearish"
    return "Mixed"


def _score_from_votes(votes: list[dict[str, Any]]) -> float | None:
    """The fusion math, factored out so the real verdict and the ``watch``
    counterfactuals score on an identical path: net Σ(sign×weight) over Σweight,
    clamped to [-1, 1]."""
    total = sum(v["weight"] for v in votes)
    if total <= _EPS:
        return None
    net = sum(v["sign"] * v["weight"] for v in votes)
    return max(-1.0, min(1.0, net / total))


def _score100(score: float) -> int:
    return int(round((score + 1) / 2 * 100))


# Base (full-magnitude) weight per lens — the vote weight a lens contributes once
# it resolves decisively in some direction. Mirrors the W_* constants above.
_BASE_WEIGHT = {
    "trend": W_TREND,
    "structure": W_STRUCTURE,
    "momentum": W_MOMENTUM,
    "pattern": W_PATTERN,
    "volume": W_VOLUME,
}


def _money(value: Any) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "the level"


def _pattern_lead(patterns: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """The single pattern that dominates the Pattern lens (highest verdict-scaled
    weight) — the one the counterfactual "if it confirmed" reasons about."""
    if not patterns:
        return None
    best: dict[str, Any] | None = None
    best_w = 0.0
    for p in patterns:
        ptype = str(p.get("type") or "neutral").lower()
        if ptype not in ("bullish", "bearish"):
            continue
        validation = p.get("validation") or {}
        factor = _VERDICT_FACTOR.get(validation.get("verdict"), 0.5)
        conf = validation.get("adjustedConfidence")
        if not isinstance(conf, (int, float)):
            conf = p.get("confidence") if isinstance(p.get("confidence"), (int, float)) else 0.5
        w = factor * float(conf)
        if w > best_w:
            best_w, best = w, p
    return best


def _contrib_phrase(contrib: dict[str, Any]) -> str | None:
    """Render one Risk-agent contribution as a concrete, threshold-bearing clause."""
    check = contrib.get("check")
    value = contrib.get("value")
    threshold = contrib.get("threshold")
    if check == "key_level":
        if isinstance(value, (int, float)) and isinstance(threshold, (int, float)):
            return f"key level at {value:.0f}% of POC vs ≥{threshold:.0f}% needed"
        return "the key level reclaiming a real volume node"
    if check == "breakout_rvol":
        if isinstance(value, (int, float)) and isinstance(threshold, (int, float)):
            return f"breakout volume {value:.1f}× vs ≥{threshold:.1f}× needed"
        return "a volume-backed breakout"
    if check == "obv":
        return "OBV aligning with the pattern"
    if check == "price_obv_divergence":
        return "OBV turning to back the price move"
    if check == "triangle":
        return "volume contracting into the apex"
    return None


def _pattern_preconditions(lead: dict[str, Any]) -> list[str]:
    """What it would take for the lead pattern to flip to a *confirmed* vote: a
    volume-backed break of its key level, plus its single worst pending check."""
    validation = lead.get("validation") or {}
    key = lead.get("keyLevel") or {}
    label = key.get("label") or "key level"
    price = key.get("price")
    out: list[str] = []
    rvol_thr = BREAKOUT_RVOL_HINT
    if price is not None:
        out.append(f"a confirmed break of the {label} at {_money(price)} on ≥{rvol_thr:.1f}× volume")
    else:
        out.append(f"a confirmed break of the {label} on ≥{rvol_thr:.1f}× volume")
    contribs = validation.get("contributions") or []
    negs = [c for c in contribs if isinstance(c.get("delta"), (int, float)) and c["delta"] < 0]
    if negs:
        dom = min(negs, key=lambda c: c["delta"])
        if dom.get("check") != "breakout_rvol":
            phrase = _contrib_phrase(dom)
            if phrase:
                out.append(phrase)
    return out


def _latent(agent: str, signals: dict[str, Any]) -> tuple[int, float, list[str]] | None:
    """A lens's *latent* resolution: the (direction, full-magnitude weight,
    preconditions) it would take on if its underlying signal resolved decisively.
    Returns None when the underlying data can't imply a direction."""
    if agent == "volume":
        obv = (signals.get("volume") or {}).get("obvSlopePct")
        if not isinstance(obv, (int, float)) or obv == 0:
            return None
        if obv > 0:
            return 1, _BASE_WEIGHT["volume"], ["OBV slope turning positive (accumulation)"]
        return -1, _BASE_WEIGHT["volume"], ["OBV slope turning negative (distribution)"]
    if agent == "trend":
        trend = signals.get("trend") or {}
        ma = trend.get("maStack")
        slope = trend.get("slopePctPerYr")
        cross = trend.get("crossState")
        if ma == "bullish":
            return 1, _BASE_WEIGHT["trend"], ["the 50/200-day MA stack holding bullish"]
        if ma == "bearish":
            return -1, _BASE_WEIGHT["trend"], ["the 50/200-day MA stack turning bearish"]
        if isinstance(slope, (int, float)) and slope != 0:
            if slope > 0:
                return 1, _BASE_WEIGHT["trend"], ["the trend slope turning decisively up"]
            return -1, _BASE_WEIGHT["trend"], ["the trend slope rolling over"]
        if cross == "golden":
            return 1, _BASE_WEIGHT["trend"], ["a 50/200 golden cross"]
        if cross == "death":
            return -1, _BASE_WEIGHT["trend"], ["a 50/200 death cross"]
        return None
    if agent == "structure":
        s = str((signals.get("swing") or {}).get("structure") or "").lower()
        if "uptrend" in s or "rising" in s:
            return 1, _BASE_WEIGHT["structure"], ["structure confirming higher highs & higher lows"]
        if "downtrend" in s or "falling" in s:
            return -1, _BASE_WEIGHT["structure"], ["structure breaking to lower highs & lower lows"]
        return None
    if agent == "momentum":
        momentum = signals.get("momentum") or {}
        state = (momentum.get("macd") or {}).get("state")
        rsi = momentum.get("rsi14")
        if state == "bullish":
            return 1, _BASE_WEIGHT["momentum"], ["MACD crossing bullish"]
        if state == "bearish":
            return -1, _BASE_WEIGHT["momentum"], ["MACD rolling over bearish"]
        if isinstance(rsi, (int, float)):
            if rsi >= 50:
                return 1, _BASE_WEIGHT["momentum"], ["RSI reclaiming the 55 line"]
            return -1, _BASE_WEIGHT["momentum"], ["RSI losing the 45 line"]
        return None
    if agent == "pattern":
        lead = _pattern_lead(signals.get("patterns"))
        if not lead:
            return None
        ptype = str(lead.get("type") or "neutral").lower()
        direction = 1 if ptype == "bullish" else -1 if ptype == "bearish" else 0
        if direction == 0:
            return None
        # A confirmed verdict keeps the pattern's own shape-confidence but drops the
        # verdict discount (factor → 1.0), so the resolved weight matches the real
        # _pattern_vote path: W_PATTERN × min(1, confidence).
        conf = lead.get("confidence")
        if not isinstance(conf, (int, float)):
            validation = lead.get("validation") or {}
            conf = validation.get("adjustedConfidence")
            if not isinstance(conf, (int, float)):
                conf = 0.5
        weight = _BASE_WEIGHT["pattern"] * min(1.0, max(0.0, float(conf)))
        return direction, weight, _pattern_preconditions(lead)
    return None


_LENS_LABEL = {
    "trend": "Trend",
    "structure": "Structure",
    "momentum": "Momentum",
    "pattern": "Pattern",
    "volume": "Volume",
}


def _build_watch(
    votes: list[dict[str, Any]],
    signals: dict[str, Any],
    score: float,
    bias: str,
) -> dict[str, Any] | None:
    """Find the single highest-impact *pending* lens whose resolution would move
    the fused bias into a new band, and phrase it precisely.

    Only lenses not already pushing toward a more decisive read are candidates
    (neutral or conflicting). Each is resolved to its full-magnitude *latent*
    direction and re-scored on the identical fusion path. The signed Δscore says
    whether the swing lifts the bias (a "Watch") or drops it (a "Risk"); clearing
    a vetoed *bearish* pattern, for instance, drops confluence rather than lifting
    it, so we never treat "veto cleared" as automatically bullish.
    """
    bias_sign = 1 if score > 0 else -1 if score < 0 else 0
    candidates: list[dict[str, Any]] = []
    for i, v in enumerate(votes):
        # Skip lenses already agreeing with the bias — they aren't what's holding
        # the verdict back from the next band.
        if bias_sign != 0 and v["sign"] == bias_sign:
            continue
        lat = _latent(v["agent"], signals)
        if lat is None:
            continue
        ldir, lweight, preconds = lat
        if ldir == 0 or not preconds:
            continue
        cf_votes = [dict(x) for x in votes]
        cf_votes[i] = {**v, "sign": int(ldir), "weight": round(max(0.0, lweight), 3)}
        cf_score = _score_from_votes(cf_votes)
        if cf_score is None:
            continue
        cf_bias = _bias_from_score(cf_score)
        if cf_bias == bias:
            # No band change → not a meaningful "watch".
            continue
        delta = cf_score - score
        candidates.append({
            "agent": v["agent"],
            "direction": "up" if delta > 0 else "down",
            "absDelta": abs(delta),
            "nextBias": cf_bias,
            "ifResolvedScore100": _score100(cf_score),
            "preconditions": preconds,
        })

    if not candidates:
        return None

    # Prefer the strongest *constructive* (upward) catalyst — what to watch for to
    # advance the bias. Only when nothing lifts the band do we surface the largest
    # downside (a "Risk"). This is what keeps DFRYF's watch on the neutral Volume
    # lens (OBV) rather than on "clearing" its bearish pattern veto (which drops it).
    ups = [c for c in candidates if c["direction"] == "up"]
    pool = ups if ups else candidates
    best = max(pool, key=lambda c: c["absDelta"])

    joined = " and ".join(best["preconditions"])
    if best["direction"] == "up":
        headline = f"Watch: {joined} would lift confluence to {best['nextBias']} (~{best['ifResolvedScore100']})."
    else:
        headline = f"Risk: {joined} would drop confluence to {best['nextBias']} (~{best['ifResolvedScore100']})."

    return {
        "limitingLens": _LENS_LABEL.get(best["agent"], best["agent"]),
        "direction": best["direction"],
        "nextBias": best["nextBias"],
        "ifResolvedScore100": best["ifResolvedScore100"],
        "preconditions": best["preconditions"],
        "headline": headline,
    }


def compute_confluence(signals: dict[str, Any] | None) -> dict[str, Any] | None:
    """Fuse the technical lenses in ``signals`` into a single confluence verdict."""
    if not signals:
        return None

    votes = [
        v
        for v in (
            _trend_vote(signals.get("trend")),
            _structure_vote(signals.get("swing")),
            _momentum_vote(signals.get("momentum")),
            _pattern_vote(signals.get("patterns")),
            _volume_vote(signals.get("volume"), signals.get("volumeProfile")),
        )
        if v is not None and v["weight"] > _EPS
    ]
    if not votes:
        return None

    total_weight = sum(v["weight"] for v in votes)
    if total_weight <= _EPS:
        return None
    score = _score_from_votes(votes)
    if score is None:
        return None
    bias = _bias_from_score(score)
    bias_sign = 1 if score > 0 else -1 if score < 0 else 0

    directional = [v for v in votes if v["sign"] != 0]
    if bias_sign != 0:
        agreements = [v for v in directional if v["sign"] == bias_sign]
        conflicts = [v for v in directional if v["sign"] == -bias_sign]
    else:
        agreements = []
        conflicts = directional

    agree_weight = sum(v["weight"] for v in agreements)
    directional_weight = sum(v["weight"] for v in directional) or _EPS
    alignment = round(agree_weight / directional_weight, 2)

    conviction = abs(score) * 0.6 + alignment * 0.4
    if conviction >= 0.66 and len(directional) >= 2:
        strength = "strong"
    elif conviction >= 0.4:
        strength = "moderate"
    else:
        strength = "weak"

    summary = _summary(bias, strength, agreements, conflicts)
    message = _message(bias, agreements, conflicts)
    watch = _build_watch(votes, signals, score, bias)

    return {
        "bias": bias,
        "score": round(score, 3),
        "score100": int(round((score + 1) / 2 * 100)),
        "strength": strength,
        "alignment": alignment,
        "agreeCount": len(agreements),
        "conflictCount": len(conflicts),
        "totalSignals": len(votes),
        "votes": votes,
        "agreements": [v["label"] for v in agreements],
        "conflicts": [v["label"] for v in conflicts],
        # Confluence-aware Tech Stance (replaces the Fib-only stance when present).
        "stance": bias,
        "summary": summary,
        "message": message,
        # Highest-impact pending condition that would move the bias to the next
        # band (signed: a "Watch" lift or a "Risk" drop). Absent when nothing does.
        "watch": watch,
    }


def _summary(
    bias: str, strength: str, agreements: list[dict], conflicts: list[dict]
) -> str:
    n_total = len(agreements) + len(conflicts)
    if not n_total:
        return f"{bias} — no directional signals."
    return (
        f"{strength.capitalize()} {bias.lower()} confluence: "
        f"{len(agreements)}/{n_total} signals align"
        + (f", {len(conflicts)} dissent" if conflicts else "")
        + "."
    )


def _message(bias: str, agreements: list[dict], conflicts: list[dict]) -> str:
    agree_txt = "; ".join(v["label"] for v in agreements) or "—"
    parts = [f"{bias}. Agreeing: {agree_txt}."]
    if conflicts:
        parts.append("Conflicts: " + "; ".join(v["label"] for v in conflicts) + ".")
    return " ".join(parts)
