"""Portfolio Intent — inferred from holdings + planned-trade geometry, optional override.

Classes (user taxonomy):
  tactical         — watch/light hold; buy≈sell size (swing / speculative)
  accumulate       — watch/light hold; buy≫sell at higher sell (build + harvest peaks)
  core             — material hold; small opportunistic buy≈sell
  core_accumulate  — material hold; buy≫sell (compound + light trim)
  divest           — held; no add plan; significant sell plan
"""

from __future__ import annotations

from typing import Any

INTENT_CODES = (
    "tactical",
    "accumulate",
    "core",
    "core_accumulate",
    "divest",
)

INTENT_LABELS = {
    "tactical": "Tactical / speculative",
    "accumulate": "Accumulate & harvest",
    "core": "Core + opportunistic",
    "core_accumulate": "Core accumulate / light trim",
    "divest": "Divest",
}

# Sell plan ≥ this fraction of held (with no buy plan) → divest.
DIVEST_SELL_FRAC = 0.25

# Soft Fit alignment nudge (points within Portfolio Fit 0–20).
FIT_INTENT_NUDGE_CAP = 2.0

# Tax & Trim harvest lean (added to candidate rank / trim score).
HARVEST_LEAN = {
    "tactical": 4.0,
    "accumulate": 2.0,
    "core": 0.0,
    "core_accumulate": -2.0,
    "divest": 5.0,
}
HARVEST_LEAN_TRIM_BONUS = 1.0  # when sell ≪ held on core intents
HARVEST_LEAN_CAP = 5.0


def _f(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        amount = float(value)
    except (TypeError, ValueError):
        return None
    return amount if amount == amount else None


def normalize_intent(code: Any) -> str | None:
    if code is None or code == "":
        return None
    c = str(code).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "core_accum": "core_accumulate",
        "coreaccumulate": "core_accumulate",
        "long_term": "core",
        "lt_hold": "core",
        "swing": "tactical",
        "speculative": "tactical",
        "exit": "divest",
        "reduce": "divest",
    }
    c = aliases.get(c, c)
    return c if c in INTENT_CODES else None


def intent_label(code: str | None) -> str | None:
    n = normalize_intent(code)
    return INTENT_LABELS.get(n) if n else None


def infer_intent(
    *,
    held: float | None,
    buy_qty: float | None,
    sell_qty: float | None,
    buy_price: float | None = None,
    sell_price: float | None = None,
) -> str:
    """Deduce Intent from position size vs planned trade legs."""
    h = max(0.0, float(held or 0))
    buy = max(0.0, float(buy_qty or 0))
    sell = max(0.0, float(sell_qty or 0))
    plan = max(buy, sell)

    # Divest: holdings exist, no add plan, significant sell plan.
    if h > 0 and buy <= 0 and sell > 0 and (sell / h) >= DIVEST_SELL_FRAC:
        return "divest"

    # Material core if held dominates the planned legs (or no plan).
    is_core = h > 0 and (plan <= 0 or h >= max(plan * 2.0, 50.0))

    sell_vs_buy = (sell / buy) if buy > 0 else None
    price_harvest = (
        buy_price is not None
        and sell_price is not None
        and float(buy_price) > 0
        and float(sell_price) >= float(buy_price) * 1.05
    )

    if not is_core:
        if buy > 0 and sell > 0:
            if sell_vs_buy is not None and sell_vs_buy <= 0.35:
                return "accumulate"
            if abs(buy - sell) / max(buy, sell) <= 0.25:
                return "tactical"
            if sell < buy:
                return "accumulate"
            return "tactical"
        if buy > 0 and sell <= 0:
            return "accumulate"
        if sell > 0 and buy <= 0:
            return "tactical"
        return "tactical"

    # Core territory
    if buy > 0 and sell > 0:
        if sell_vs_buy is not None and sell_vs_buy <= 0.35:
            return "core_accumulate"
        if abs(buy - sell) / max(buy, sell) <= 0.35:
            return "core"
        if sell < buy:
            return "core_accumulate"
        return "core"
    if buy > 0 and sell <= 0:
        return "core_accumulate"
    if sell > 0 and h > 0 and sell / h < DIVEST_SELL_FRAC:
        return "core_accumulate" if price_harvest or buy <= 0 else "core"
    return "core"


def resolve_intent(
    *,
    held: float | None,
    buy_qty: float | None,
    sell_qty: float | None,
    buy_price: float | None = None,
    sell_price: float | None = None,
    override: Any = None,
) -> dict[str, Any]:
    inferred = infer_intent(
        held=held,
        buy_qty=buy_qty,
        sell_qty=sell_qty,
        buy_price=buy_price,
        sell_price=sell_price,
    )
    ov = normalize_intent(override)
    code = ov or inferred
    return {
        "code": code,
        "label": INTENT_LABELS[code],
        "inferred": inferred,
        "override": ov,
        "source": "override" if ov else "inferred",
    }


def fit_intent_nudge(
    *,
    intent_code: str | None,
    action: str | None,
    held: float | None = None,
    sell_qty: float | None = None,
) -> tuple[float, list[str]]:
    """Soft Fit points when SAI action aligns with portfolio Intent."""
    code = normalize_intent(intent_code)
    act = str(action or "hold").lower()
    if not code:
        return 0.0, []
    delta = 0.0
    factors: list[str] = []
    label = INTENT_LABELS[code]

    if code == "tactical":
        if act in ("sell", "watch"):
            delta = 2.0
            factors.append(f"Intent {label} aligns with {act} → fit +2")
        elif act == "buy" and float(held or 0) <= 0:
            delta = 1.0
            factors.append(f"Intent {label} — initiating swing → fit +1")
    elif code == "accumulate":
        if act in ("buy", "watch"):
            delta = 2.0
            factors.append(f"Intent {label} aligns with {act} → fit +2")
        elif act == "sell":
            delta = -1.0
            factors.append(f"Intent {label} vs full sell lean → fit −1")
    elif code == "core":
        if act in ("hold", "watch"):
            delta = 1.0
            factors.append(f"Intent {label} — hold/watch fit +1")
        elif act == "sell":
            h = float(held or 0)
            s = float(sell_qty or 0)
            if h > 0 and s > 0 and s / h <= 0.2:
                delta = 1.0
                factors.append(f"Intent {label} — light opportunistic trim → fit +1")
            else:
                delta = -2.0
                factors.append(f"Intent {label} vs large sell → fit −2")
        elif act == "buy":
            delta = 1.0
            factors.append(f"Intent {label} — opportunistic add → fit +1")
    elif code == "core_accumulate":
        if act in ("buy", "watch"):
            delta = 2.0
            factors.append(f"Intent {label} aligns with {act} → fit +2")
        elif act == "sell":
            h = float(held or 0)
            s = float(sell_qty or 0)
            if h > 0 and s > 0 and s / h <= 0.15:
                delta = 1.0
                factors.append(f"Intent {label} — light winner-trim → fit +1")
            else:
                delta = -2.0
                factors.append(f"Intent {label} vs large sell → fit −2")
    elif code == "divest":
        if act == "sell":
            delta = 2.0
            factors.append(f"Intent {label} aligns with sell → fit +2")
        elif act == "watch":
            delta = 1.0
            factors.append(f"Intent {label} — watch/exit path → fit +1")
        elif act == "buy":
            delta = -2.0
            factors.append(f"Intent {label} vs buy → fit −2")

    delta = max(-FIT_INTENT_NUDGE_CAP, min(FIT_INTENT_NUDGE_CAP, delta))
    return delta, factors


def harvest_intent_lean(
    *,
    intent_code: str | None,
    is_trim: bool = False,
    held: float | None = None,
    sell_qty: float | None = None,
) -> tuple[float, str | None]:
    """Capped Tax-Win / trim ranking lean from Intent (tactical/divest more harvestable)."""
    code = normalize_intent(intent_code)
    if not code:
        return 0.0, None
    lean = float(HARVEST_LEAN.get(code, 0.0))
    h = float(held or 0)
    s = float(sell_qty or 0)
    if code in ("core", "core_accumulate") and is_trim and h > 0 and s > 0 and s / h <= 0.2:
        lean += HARVEST_LEAN_TRIM_BONUS
    lean = max(-HARVEST_LEAN_CAP, min(HARVEST_LEAN_CAP, lean))
    if lean == 0:
        return 0.0, None
    sign = "+" if lean > 0 else ""
    return lean, f"Intent {INTENT_LABELS[code]} harvest lean {sign}{lean:.0f}"


def attention_for_actions(*, band_action: str, sai_action: str) -> dict[str, Any]:
    """Pay-attention when Score-band action differs from published SAI action."""

    def _norm(action: str) -> str:
        a = str(action or "hold").lower()
        if a == "hold":
            return "watch"
        return a

    band = str(band_action or "watch").lower()
    sai = str(sai_action or "hold").lower()
    nb, ns = _norm(band), _norm(sai)
    if nb == ns:
        return {
            "flag": False,
            "level": None,
            "message": None,
            "bandAction": band,
            "saiAction": sai,
        }
    opposite = (nb, ns) in (("buy", "sell"), ("sell", "buy"))
    level = "warn" if opposite else "info"
    return {
        "flag": True,
        "level": level,
        "message": (
            f"Pay attention: Score band → {band.upper()} while SAI Action is {sai.upper()}"
        ),
        "bandAction": band,
        "saiAction": sai,
    }
