"""Risk agent — volume-based validation of detected chart patterns (Phase 2).

A classic pattern's *shape* (the geometry the zig-zag matcher finds) says nothing
about whether real trading conviction backs it. This layer cross-checks each
detected pattern against volume so a hollow setup can be downgraded or vetoed
before it ever reaches the recommendation:

* **Breakout confirmation** — a confirmed break should come on expanding volume
  (RVOL ≥ ``VOLUME_BREAKOUT_RVOL``). A break on average/light volume is suspect.
* **Key-level conviction** — the reversal extreme (a double-bottom's low, a
  head's trough) should sit on a meaningful volume node. The motivating example:
  a double bottom at $95 where only ~30% of POC volume traded is a weak demand
  zone → veto.
* **OBV alignment** — On-Balance-Volume should trend with the pattern's bias
  (accumulation under a bullish pattern, distribution under a bearish one).
* **Formation contraction** — triangles should coil on *declining* volume.

Pure functions (DataFrame in, dict out) so they unit-test without the network.
The verdict is advisory: by default weak/veto patterns are flagged + down-weighted
(``RISK_PATTERN_ACTION=downgrade``); set ``RISK_PATTERN_ACTION=veto`` to drop
veto-grade patterns entirely so they can't drive a recommendation.
"""
from __future__ import annotations

import os
from typing import Any

import numpy as np
import pandas as pd

from services.volume_service import volume_at_price

# Master switch + behaviour. Downgrade keeps weak patterns visible (flagged and
# down-weighted); veto removes veto-grade ones from the result.
ENABLED = os.environ.get("ASSESSMENT_PATTERN_VOLUME", "1").lower() not in (
    "0",
    "false",
    "no",
    "off",
)
ACTION = os.environ.get("RISK_PATTERN_ACTION", "downgrade").strip().lower()

# RVOL on the breakout bar(s) needed to call a break "volume-confirmed".
BREAKOUT_RVOL = float(os.environ.get("VOLUME_BREAKOUT_RVOL", "1.3"))

# Verdict cut-offs on the 0..1 validation score.
_CONFIRM_AT = float(os.environ.get("RISK_PATTERN_CONFIRM_SCORE", "0.62"))
_VETO_BELOW = float(os.environ.get("RISK_PATTERN_VETO_SCORE", "0.40"))

# Confidence multipliers applied to the pattern's shape-confidence per verdict
# (downgrade mode). Veto-grade patterns are heavily discounted but still shown.
_CONF_FACTOR = {"confirmed": 1.0, "weak": 0.7, "veto": 0.4, "pending": 0.85}


def _aligned_series(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, list[str]] | None:
    if df is None or getattr(df, "empty", True) or "Close" not in df or "Volume" not in df:
        return None
    close = pd.to_numeric(df["Close"], errors="coerce").dropna()
    if len(close) < 25:
        return None
    vol = pd.to_numeric(df["Volume"], errors="coerce").reindex(close.index).fillna(0.0)
    dates = [d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d) for d in close.index]
    return close.astype(float), vol.astype(float), dates


def _rvol_at(vol: pd.Series, pos: int, window: int = 20) -> float | None:
    if pos < 0 or pos >= len(vol):
        return None
    lo = max(0, pos - window + 1)
    avg = float(vol.iloc[lo : pos + 1].mean())
    if avg <= 0:
        return None
    return float(vol.iloc[pos]) / avg


def _breakout_rvol(vol: pd.Series, dates: list[str], end_date: str) -> float | None:
    """Peak RVOL from the pattern's last pivot through the most recent bar — the
    window in which a genuine breakout would print its volume surge."""
    try:
        start = dates.index(end_date)
    except ValueError:
        start = len(dates) - 1
    best: float | None = None
    for pos in range(start, len(vol)):
        r = _rvol_at(vol, pos)
        if r is not None and (best is None or r > best):
            best = r
    return best


def _obv_slope_pct(close: pd.Series, vol: pd.Series, window: int = 21) -> float | None:
    direction = np.sign(close.diff().fillna(0.0))
    obv = (direction * vol).cumsum()
    win = min(window, len(obv))
    if win < 3:
        return None
    y = obv.iloc[-win:].to_numpy()
    slope = float(np.polyfit(np.arange(win), y, 1)[0])
    scale = float(np.abs(y).mean())
    return slope / scale * 100 if scale > 0 else None


def _reversal_level(pattern: dict[str, Any]) -> float | None:
    """The extreme that must show conviction: the low for a bullish reversal,
    the high for a bearish one."""
    points = pattern.get("points") or []
    prices = [p.get("price") for p in points if isinstance(p.get("price"), (int, float))]
    if not prices:
        key = pattern.get("keyLevel") or {}
        return key.get("price")
    ptype = str(pattern.get("type") or "").lower()
    if ptype == "bullish":
        return min(prices)
    if ptype == "bearish":
        return max(prices)
    return sum(prices) / len(prices)


def validate_pattern(
    pattern: dict[str, Any],
    df: pd.DataFrame,
    profile: dict[str, Any] | None,
    price: float | None,
) -> dict[str, Any] | None:
    """Return a validation block for one pattern (does not mutate it)."""
    series = _aligned_series(df)
    if series is None:
        return None
    close, vol, dates = series
    ptype = str(pattern.get("type") or "neutral").lower()
    status = str(pattern.get("status") or "").lower()
    name = str(pattern.get("name") or "")

    score = 0.5
    reasons: list[str] = []
    breakout_rvol: float | None = None

    # 1) Breakout confirmation (only meaningful once the pattern has broken out).
    if status == "confirmed":
        breakout_rvol = _breakout_rvol(vol, dates, pattern.get("endDate") or (dates[-1] if dates else ""))
        if breakout_rvol is not None:
            if breakout_rvol >= BREAKOUT_RVOL:
                score += 0.30
                reasons.append(f"Breakout on {breakout_rvol:.1f}× average volume")
            elif breakout_rvol >= 1.0:
                score += 0.10
                reasons.append(f"Breakout on modest volume ({breakout_rvol:.1f}×)")
            else:
                score -= 0.25
                reasons.append(f"Breakout lacked volume ({breakout_rvol:.1f}×) — unconvincing")
    else:
        reasons.append("Not yet broken out — volume confirmation pending")

    # 2) Conviction at the reversal extreme vs the Point of Control.
    node = None
    rev_level = _reversal_level(pattern)
    if profile and profile.get("bins") and rev_level is not None:
        node = volume_at_price(profile["bins"], rev_level)
    if node:
        pct = node.get("pctOfPoc")
        kind = node.get("node")
        zone = "low" if ptype == "bullish" else "high"  # demand vs supply zone wording
        if kind == "high":
            score += 0.20
            reasons.append(f"Key level on a high-volume node ({pct:.0f}% of POC) — strong {('demand' if ptype=='bullish' else 'supply')}")
        elif kind == "medium":
            score += 0.05
            reasons.append(f"Key level on a moderate-volume node ({pct:.0f}% of POC)")
        else:
            score -= 0.28
            reasons.append(f"Key level in a low-volume zone ({(pct or 0):.0f}% of POC) — weak {('demand' if ptype=='bullish' else 'supply')}")

    # 3) OBV alignment with the pattern's directional bias.
    obv = _obv_slope_pct(close, vol)
    if obv is not None and ptype in ("bullish", "bearish"):
        aligned = (obv >= 0) if ptype == "bullish" else (obv <= 0)
        if aligned:
            score += 0.15
            reasons.append(f"OBV confirms ({'accumulation' if ptype=='bullish' else 'distribution'})")
        else:
            score -= 0.15
            reasons.append(f"OBV diverges from a {ptype} read")

    # 4) Triangles should coil on contracting volume.
    if "triangle" in name.lower():
        contracting = _volume_contracting(vol, dates, pattern)
        if contracting is True:
            score += 0.10
            reasons.append("Volume contracting into the apex (textbook)")
        elif contracting is False:
            reasons.append("Volume not contracting — weaker triangle")

    score = round(max(0.0, min(1.0, score)), 2)

    if score < _VETO_BELOW:
        # Conviction so poor the setup is rejected outright (even while forming —
        # e.g. a double bottom on a low-volume floor).
        verdict = "veto"
    elif status != "confirmed":
        # A still-forming pattern can't be volume-confirmed until it breaks out.
        verdict = "pending"
    else:
        verdict = "confirmed" if score >= _CONFIRM_AT else "weak"

    return {
        "verdict": verdict,
        "score": score,
        "volumeConfirmed": verdict == "confirmed",
        "breakoutRvol": round(breakout_rvol, 2) if breakout_rvol is not None else None,
        "keyLevelNode": node,
        "obvSlopePct": round(obv, 2) if obv is not None else None,
        "reasons": reasons,
        "adjustedConfidence": _adjusted_confidence(pattern, verdict),
    }


def _volume_contracting(vol: pd.Series, dates: list[str], pattern: dict[str, Any]) -> bool | None:
    start = pattern.get("startDate")
    end = pattern.get("endDate")
    try:
        i0 = dates.index(start)
        i1 = dates.index(end)
    except ValueError:
        return None
    if i1 - i0 < 6:
        return None
    seg = vol.iloc[i0 : i1 + 1].to_numpy()
    if len(seg) < 6:
        return None
    slope = float(np.polyfit(np.arange(len(seg)), seg, 1)[0])
    return slope < 0


def _adjusted_confidence(pattern: dict[str, Any], verdict: str) -> float | None:
    base = pattern.get("confidence")
    if not isinstance(base, (int, float)):
        return None
    return round(float(base) * _CONF_FACTOR.get(verdict, 1.0), 2)


def validate_patterns(
    patterns: list[dict[str, Any]],
    df: pd.DataFrame,
    profile: dict[str, Any] | None,
    price: float | None,
) -> list[dict[str, Any]]:
    """Attach a ``validation`` block to each pattern. In ``veto`` mode, drop
    veto-grade patterns so they can't influence the recommendation."""
    if not patterns or not ENABLED:
        return patterns
    out: list[dict[str, Any]] = []
    for pattern in patterns:
        validation = validate_pattern(pattern, df, profile, price)
        if validation is None:
            out.append(pattern)
            continue
        if ACTION == "veto" and validation["verdict"] == "veto":
            continue
        out.append({**pattern, "validation": validation})
    return out
