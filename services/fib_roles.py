"""Fibonacci level roles and meanings (docs/PATTERNS.md §7–8).

Shared by Fib alerts, Confluence, and the SAI overlay so wording and weights
stay aligned with the documented ladder.
"""

from __future__ import annotations

from typing import Any

# role keys: high | shallow | retrace | center | golden | deep | base
_FIB_ROLE_BY_RATIO: dict[float, dict[str, str]] = {
    0.0: {
        "role": "high",
        "roleName": "High",
        "cue": "overhead resistance; reclaim needed for full recovery",
    },
    0.236: {
        "role": "shallow",
        "roleName": "Shallow",
        "cue": "minor pullback; strong trends often hold above",
    },
    0.382: {
        "role": "retrace",
        "roleName": "Retracement",
        "cue": "healthy pullback; common bounce zone in uptrend",
    },
    0.5: {
        "role": "center",
        "roleName": "Center Line",
        "cue": "bull/bear baseline — above constructive, below cautious",
    },
    0.618: {
        "role": "golden",
        "roleName": "Golden Pocket",
        "cue": "holding keeps larger up-move intact; break opens path toward Base",
    },
    0.786: {
        "role": "deep",
        "roleName": "Deep",
        "cue": "last line before full give-back",
    },
    1.0: {
        "role": "base",
        "roleName": "Base",
        "cue": "range floor / support",
    },
}

# How much each role counts in Confluence (before proximity scaling).
FIB_ROLE_WEIGHT: dict[str, float] = {
    "high": 0.8,
    "shallow": 0.35,
    "retrace": 0.5,
    "center": 0.85,
    "golden": 1.0,
    "deep": 0.7,
    "base": 0.8,
}


def ratio_from_label(label: str | None) -> float | None:
    """Parse ``61.8%`` or ``0.618`` style labels into a Fib ratio."""
    if label is None:
        return None
    text = str(label).strip()
    if not text:
        return None
    # Prefer percent form (production fib_level is "61.8%").
    if text.endswith("%"):
        try:
            return round(float(text[:-1].strip()) / 100.0, 4)
        except (TypeError, ValueError):
            return None
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    if value > 1.0:
        return round(value / 100.0, 4)
    return round(value, 4)


def describe_fib_ratio(ratio: float | None) -> dict[str, str] | None:
    if ratio is None:
        return None
    # Exact / near-exact match against known ladder steps.
    for known, meta in _FIB_ROLE_BY_RATIO.items():
        if abs(float(ratio) - known) < 1e-6:
            return dict(meta)
    return None


def describe_fib_label(label: str | None) -> dict[str, str] | None:
    return describe_fib_ratio(ratio_from_label(label))


def enrich_fib_level(level: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a copy of ``level`` with role / roleName / cue attached."""
    if not level:
        return None
    out = dict(level)
    meta = describe_fib_ratio(out.get("ratio"))
    if meta is None and out.get("label"):
        meta = describe_fib_label(str(out.get("label")))
    if meta:
        out.update(meta)
    return out


def fib_side(price: float | None, level_price: float | None) -> str | None:
    if price is None or level_price is None:
        return None
    if float(price) >= float(level_price):
        return "above"
    return "below"


def stance_hint_for_context(
    *,
    role: str | None,
    side: str | None,
    distance_pct: float | None,
    alert_proximity_pct: float = 2.0,
) -> str:
    """Map to Technical Stance language from PATTERNS.md §8.

    Proximity always yields ``alert``. Away from a level, Center Line side
    drives ``strong`` (above) vs ``cautious`` (below); other roles stay
    ``neutral`` when not in the alert band.
    """
    if isinstance(distance_pct, (int, float)) and distance_pct <= alert_proximity_pct:
        return "alert"
    if role == "center":
        if side == "above":
            return "strong"
        if side == "below":
            return "cautious"
    return "neutral"


def build_fib_context(
    *,
    level: dict[str, Any],
    price: float,
    distance_pct: float,
    alert_proximity_pct: float = 2.0,
) -> dict[str, Any]:
    """Machine-readable Fib proximity payload for alerts / SAI / Confluence."""
    enriched = enrich_fib_level(level) or dict(level)
    level_price = enriched.get("price")
    side = fib_side(price, level_price if isinstance(level_price, (int, float)) else None)
    role = enriched.get("role")
    role_name = enriched.get("roleName") or enriched.get("label") or "Fibonacci"
    cue = enriched.get("cue") or "a key Fibonacci support/resistance zone"
    hint = stance_hint_for_context(
        role=str(role) if role else None,
        side=side,
        distance_pct=distance_pct,
        alert_proximity_pct=alert_proximity_pct,
    )
    ratio = enriched.get("ratio")
    if ratio is None:
        ratio = ratio_from_label(enriched.get("label"))
    return {
        "ratio": ratio,
        "role": role,
        "roleName": role_name,
        "label": enriched.get("label"),
        "price": level_price,
        "side": side,
        "distancePct": round(float(distance_pct), 2),
        "stanceHint": hint,
        "cue": cue,
    }


def format_fib_proximity_message(
    symbol: str,
    price: float,
    context: dict[str, Any],
) -> str:
    """Compact alert text; wrap the level title in ``**…**`` for UI bolding."""
    label = context.get("label") or "Fibonacci"
    role_name = context.get("roleName") or "level"
    # Avoid "61.8% Golden Pocket" repeating percent when role already includes it.
    level_title = f"{label} {role_name}" if str(label) not in str(role_name) else str(role_name)
    level_price = context.get("price")
    price_txt = (
        f"${float(level_price):.2f}"
        if isinstance(level_price, (int, float))
        else "the level"
    )
    side = context.get("side")
    if side == "above":
        side_txt = "just above"
    elif side == "below":
        side_txt = "just below"
    else:
        side_txt = "near"
    dist = context.get("distancePct")
    dist_txt = f"{float(dist):.2f}%" if isinstance(dist, (int, float)) else "—"
    cue = context.get("cue") or "watch for hold or break"
    return (
        f"{symbol} at ${float(price):.2f} is {side_txt} **{level_title}** "
        f"at {price_txt} ({dist_txt}) — {cue}."
    )


def fib_context_from_alert(alert: dict[str, Any]) -> dict[str, Any] | None:
    """Rebuild structured Fib context from a stored alert row/dict."""
    if (alert.get("type") or alert.get("alert_type")) != "fib_proximity":
        return None
    label = alert.get("fibLevel") or alert.get("fib_level")
    meta = describe_fib_label(label if label is None else str(label))
    price = alert.get("price")
    level_price = alert.get("referenceValue")
    if level_price is None:
        level_price = alert.get("reference_value")
    distance_pct = None
    if isinstance(price, (int, float)) and isinstance(level_price, (int, float)) and price:
        distance_pct = abs(float(price) - float(level_price)) / float(price) * 100
    level = {
        "label": label,
        "ratio": ratio_from_label(str(label) if label is not None else None),
        "price": level_price,
    }
    if meta:
        level.update(meta)
    if not isinstance(price, (int, float)):
        # Still return role metadata for factor wording.
        return {
            "ratio": level.get("ratio"),
            "role": level.get("role"),
            "roleName": level.get("roleName") or label or "Fibonacci",
            "label": label,
            "price": level_price,
            "side": None,
            "distancePct": None,
            "stanceHint": "alert",
            "cue": level.get("cue") or "a key Fibonacci support/resistance zone",
        }
    return build_fib_context(
        level=level,
        price=float(price),
        distance_pct=float(distance_pct or 0.0),
    )
