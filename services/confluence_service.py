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
        if obv > 1:
            direction = 1
        elif obv < -1:
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
    net = sum(v["sign"] * v["weight"] for v in votes)
    score = max(-1.0, min(1.0, net / total_weight))
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
