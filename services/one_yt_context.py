"""1YT (screener upside) alert context — portfolio median, pattern, ATR.

Mirrors the Fib enrichment pattern: compact human message + machine payload
for SAI / future Confluence consumers.

Categories (chips that replace the old single "Screener Upside" type):
  chance  — confirmed bullish setup + Street gap
  lean    — bullish setup developing
  stretch — outlier gap without confirmed setup (lottery / hope)
  watch   — clears the upside gate but not extreme
"""

from __future__ import annotations

import os
import statistics
from typing import Any

# Risk-agent verdict weights for picking a lead pattern (same spirit as confluence).
_VERDICT_FACTOR = {
    "confirmed": 1.0,
    "weak": 0.6,
    "pending": 0.45,
    "veto": 0.1,
    "stale": 0.05,
}

# Chip categories → persisted alert_type (Trade-gate style).
ONE_YT_ALERT_TYPES: dict[str, str] = {
    "chance": "one_yt_chance",
    "lean": "one_yt_lean",
    "stretch": "one_yt_stretch",
    "watch": "one_yt_watch",
}
ONE_YT_TYPE_TO_CATEGORY: dict[str, str] = {
    **{alert_type: cat for cat, alert_type in ONE_YT_ALERT_TYPES.items()},
    "screener_upside": "watch",  # legacy rows until re-evaluated
}
ONE_YT_ALERT_FAMILY: frozenset[str] = frozenset(ONE_YT_TYPE_TO_CATEGORY)

# Stretch = risk stance AND at least one of these extremes.
STRETCH_MEDIAN_MULT = float(os.environ.get("ONE_YT_STRETCH_MEDIAN_MULT", "2.0"))
STRETCH_ATR_UNITS = float(os.environ.get("ONE_YT_STRETCH_ATR_UNITS", "20"))
STRETCH_UPSIDE_PCT = float(os.environ.get("ONE_YT_STRETCH_UPSIDE_PCT", "80"))


def is_one_yt_alert_type(alert_type: str | None) -> bool:
    return str(alert_type or "") in ONE_YT_ALERT_FAMILY


def category_from_alert_type(alert_type: str | None) -> str | None:
    return ONE_YT_TYPE_TO_CATEGORY.get(str(alert_type or ""))


def alert_type_for_category(category: str) -> str:
    return ONE_YT_ALERT_TYPES.get(category, ONE_YT_ALERT_TYPES["watch"])


def categorize_one_yt(
    *,
    stance: str | None,
    vs_median: float | None = None,
    atr_units_val: float | None = None,
    upside: float | None = None,
) -> str:
    """Map stance + extremity → chance | lean | stretch | watch."""
    if stance == "chance":
        return "chance"
    if stance == "lean_chance":
        return "lean"
    stretchy = False
    if isinstance(vs_median, (int, float)) and vs_median >= STRETCH_MEDIAN_MULT:
        stretchy = True
    if isinstance(atr_units_val, (int, float)) and atr_units_val >= STRETCH_ATR_UNITS:
        stretchy = True
    if isinstance(upside, (int, float)) and upside >= STRETCH_UPSIDE_PCT:
        stretchy = True
    if stance == "risk" and stretchy:
        return "stretch"
    return "watch"


def upside_pct(price: float | None, target: float | None) -> float | None:
    if not isinstance(price, (int, float)) or not isinstance(target, (int, float)):
        return None
    if price <= 0:
        return None
    return round((float(target) - float(price)) / float(price) * 100, 2)


def portfolio_median_upside(screener_input: dict[str, dict[str, Any]]) -> float | None:
    """Median 1YT upside across names that have price + analyst/personal target."""
    values: list[float] = []
    for details in (screener_input or {}).values():
        price = details.get("currentPrice")
        target = details.get("analystTarget1y") or details.get("targetPrice")
        pct = upside_pct(price, target)
        if pct is not None:
            values.append(pct)
    if not values:
        return None
    return round(float(statistics.median(values)), 2)


def vs_median_multiple(upside: float | None, median: float | None) -> float | None:
    if upside is None or median is None or median <= 0:
        return None
    return round(float(upside) / float(median), 2)


def atr_units(upside: float | None, atr_pct: float | None) -> float | None:
    """How many daily ATR moves to close the Street gap (rough)."""
    if upside is None or atr_pct is None or atr_pct <= 0:
        return None
    return round(float(upside) / float(atr_pct), 1)


def lead_pattern(patterns: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """Highest verdict-scaled pattern — name/type/verdict for the alert cue."""
    if not patterns:
        return None
    best: dict[str, Any] | None = None
    best_w = 0.0
    for p in patterns:
        validation = p.get("validation") or {}
        verdict = validation.get("verdict")
        factor = _VERDICT_FACTOR.get(verdict, 0.4)
        conf = validation.get("adjustedConfidence")
        if not isinstance(conf, (int, float)):
            conf = p.get("confidence") if isinstance(p.get("confidence"), (int, float)) else 0.5
        w = factor * float(conf)
        if w > best_w:
            best_w = w
            best = {
                "name": p.get("name") or "Pattern",
                "type": str(p.get("type") or "neutral").lower(),
                "verdict": verdict,
                "confidence": round(float(conf), 2),
            }
    return best


def stance_hint_for_one_yt(
    *,
    upside: float | None,
    pattern: dict[str, Any] | None,
) -> str:
    """chance | lean_chance | risk | watch — compact risk/reward read."""
    ptype = (pattern or {}).get("type")
    verdict = (pattern or {}).get("verdict")
    if ptype == "bullish" and verdict == "confirmed":
        return "chance"
    if ptype == "bullish" and verdict in ("weak", "pending"):
        return "lean_chance"
    if ptype == "bearish" or verdict == "veto":
        return "risk"
    if not pattern:
        return "risk" if isinstance(upside, (int, float)) and upside >= 50 else "watch"
    return "watch"


def cue_for_one_yt(stance: str, pattern: dict[str, Any] | None) -> str:
    if stance == "chance":
        return "bullish setup + Street gap"
    if stance == "lean_chance":
        name = (pattern or {}).get("name") or "pattern"
        return f"{name} forming — Street gap with setup developing"
    if stance == "risk":
        if pattern and pattern.get("type") == "bearish":
            return "Street gap against bearish structure (risk)"
        if pattern and pattern.get("verdict") == "veto":
            return "Street gap but pattern volume-vetoed (risk)"
        return "Street gap without confirmed setup (risk)"
    return "monitor Street gap vs tape"


def build_one_yt_context(
    *,
    price: float,
    target: float,
    upside: float,
    portfolio_median: float | None = None,
    atr_pct: float | None = None,
    pattern: dict[str, Any] | None = None,
) -> dict[str, Any]:
    mult = vs_median_multiple(upside, portfolio_median)
    units = atr_units(upside, atr_pct)
    stance = stance_hint_for_one_yt(upside=upside, pattern=pattern)
    category = categorize_one_yt(
        stance=stance,
        vs_median=mult,
        atr_units_val=units,
        upside=upside,
    )
    return {
        "upsidePct": round(float(upside), 2),
        "target": round(float(target), 2),
        "portfolioMedianPct": portfolio_median,
        "vsMedianMultiple": mult,
        "atrPct": round(float(atr_pct), 2) if isinstance(atr_pct, (int, float)) else None,
        "atrUnits": units,
        "pattern": pattern,
        "stanceHint": stance,
        "category": category,
        "alertType": alert_type_for_category(category),
        "cue": cue_for_one_yt(stance, pattern),
    }


def format_one_yt_message(symbol: str, price: float, ctx: dict[str, Any]) -> str:
    """Compact 1YT alert; ``**…**`` marks the headline gap for UI bolding."""
    upside = ctx.get("upsidePct")
    target = ctx.get("target")
    upside_txt = f"{float(upside):.1f}%" if isinstance(upside, (int, float)) else "—"
    target_txt = f"${float(target):.2f}" if isinstance(target, (int, float)) else "1YT"

    parts = [
        f"{symbol} at ${float(price):.2f} is **{upside_txt} below 1YT** ({target_txt})"
    ]

    mult = ctx.get("vsMedianMultiple")
    median = ctx.get("portfolioMedianPct")
    if isinstance(mult, (int, float)) and isinstance(median, (int, float)):
        parts.append(f"{mult:.1f}× portfolio median ({median:.0f}%)")

    mid: list[str] = []
    pattern = ctx.get("pattern") or {}
    if pattern.get("name"):
        verdict = pattern.get("verdict")
        verdict_txt = f" ({verdict})" if verdict else ""
        mid.append(f"{pattern['name']}{verdict_txt}")
    else:
        mid.append("no confirmed pattern")

    units = ctx.get("atrUnits")
    atr_pct = ctx.get("atrPct")
    if isinstance(units, (int, float)):
        atr_bit = f"gap ≈ {units:.0f}× ATR"
        if isinstance(atr_pct, (int, float)):
            atr_bit += f" ({atr_pct:.1f}%)"
        mid.append(atr_bit)

    cue = ctx.get("cue") or "monitor Street gap"
    return f"{' · '.join(parts)} — {'; '.join(mid)} — {cue}."


def one_yt_context_from_alert(alert: dict[str, Any]) -> dict[str, Any] | None:
    """Rebuild a minimal 1YT payload from stored alert fields (no network)."""
    alert_type = alert.get("type") or alert.get("alert_type")
    if not is_one_yt_alert_type(str(alert_type) if alert_type is not None else None):
        return None
    price = alert.get("price")
    target = alert.get("referenceValue")
    if target is None:
        target = alert.get("reference_value")
    pct = upside_pct(price, target)
    if pct is None or not isinstance(price, (int, float)) or not isinstance(target, (int, float)):
        return None
    # Prefer richer payload if already attached (fresh create path).
    existing = alert.get("oneYt")
    if isinstance(existing, dict) and existing.get("upsidePct") is not None:
        if not existing.get("category"):
            existing = {
                **existing,
                "category": category_from_alert_type(str(alert_type)),
                "alertType": alert_type,
            }
        return existing
    ctx = build_one_yt_context(price=float(price), target=float(target), upside=pct)
    # Prefer category encoded in the persisted alert_type when tape context is gone.
    cat = category_from_alert_type(str(alert_type))
    if cat:
        ctx["category"] = cat
        ctx["alertType"] = alert_type_for_category(cat)
    return ctx
