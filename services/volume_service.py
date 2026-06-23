"""Volume analytics computed from the same cached daily OHLCV history.

Phase 0 (metrics) + Phase 1 (volume profile / Point of Control) of the
volume-confirmation work. Everything here is **pure** (DataFrame in, dict out)
so it is unit-testable without the network and rides the history DataFrame that
``TechnicalSignalsService`` already fetches and caches — adding volume analysis
needs **no extra Yahoo calls** because ``df["Volume"]`` is already present and was
simply discarded before.

Two products:

* ``volume_block(df)`` — point-in-time liquidity context: volume MAs, relative
  volume (RVOL), an On-Balance-Volume trend, and a coarse ``state`` label.
* ``volume_profile(df)`` — an approximate **volume profile** with Point of
  Control (POC) and Value Area (VAH/VAL).

POC caveat: a true tick-level Point of Control needs intraday volume-at-price
data that no free feed provides. We approximate it from daily bars by spreading
each day's ``Volume`` uniformly across that day's High–Low range into fixed price
bins. The bin with the most accumulated volume is the POC; the smallest
contiguous span of bins holding ~``VALUE_AREA_PCT`` of volume is the Value Area.
That is enough to judge whether a price/level sits on a high-volume node (strong
support/resistance) or a low-volume gap (prone to fast moves) — which is what the
later Risk/Confluence agents need to validate a pattern.
"""
from __future__ import annotations

import os
from typing import Any

import numpy as np
import pandas as pd

# Profile knobs (env-tunable, same style as the rest of the technical stack).
PROFILE_LOOKBACK = max(20, int(os.environ.get("VOLUME_PROFILE_LOOKBACK", "252")))
PROFILE_BINS = max(6, int(os.environ.get("VOLUME_PROFILE_BINS", "24")))
VALUE_AREA_PCT = min(0.95, max(0.5, float(os.environ.get("VOLUME_VALUE_AREA_PCT", "0.70"))))


def _round(value: float | None, ndigits: int = 2) -> float | None:
    if value is None or (isinstance(value, float) and (np.isnan(value) or np.isinf(value))):
        return None
    return round(float(value), ndigits)


def _clean_volume(df: pd.DataFrame) -> "pd.Series | None":
    if df is None or getattr(df, "empty", True) or "Volume" not in df:
        return None
    vol = pd.to_numeric(df["Volume"], errors="coerce").fillna(0.0).astype(float)
    if vol.empty or float(vol.sum()) <= 0:
        return None
    return vol


def volume_block(df: pd.DataFrame) -> dict[str, Any] | None:
    """Liquidity context for the current bar: MAs, RVOL, OBV trend, state label."""
    vol = _clean_volume(df)
    if vol is None or len(vol) < 5:
        return None
    close = pd.to_numeric(df["Close"], errors="coerce").reindex(vol.index)

    last = float(vol.iloc[-1])
    avg20 = float(vol.iloc[-20:].mean()) if len(vol) >= 20 else float(vol.mean())
    avg50 = float(vol.iloc[-50:].mean()) if len(vol) >= 50 else float(vol.mean())
    rvol = last / avg20 if avg20 > 0 else None

    # Volume regime from the 20- vs 50-day average (rising participation vs drying up).
    trend = None
    if avg50 > 0:
        ratio = avg20 / avg50
        trend = "rising" if ratio >= 1.05 else "falling" if ratio <= 0.95 else "flat"

    obv_slope_pct = _obv_slope_pct(close, vol)

    state = "normal"
    if rvol is not None:
        if rvol >= 2.0:
            state = "surging"
        elif rvol >= 1.3:
            state = "elevated"
        elif rvol <= 0.6:
            state = "light"

    return {
        "lastVolume": int(last),
        "avgVolume20": int(avg20),
        "avgVolume50": int(avg50),
        "rvol": _round(rvol, 2),
        "trend": trend,
        "obvSlopePct": obv_slope_pct,
        "state": state,
    }


def _obv_slope_pct(close: pd.Series, vol: pd.Series, window: int = 21) -> float | None:
    """Slope of On-Balance-Volume over ``window`` bars, as % of mean |OBV|.

    Positive = net accumulation, negative = net distribution. Normalising by the
    mean magnitude keeps it comparable across symbols of very different volume.
    """
    close = close.astype(float)
    if close.isna().all() or len(close) < 3:
        return None
    direction = np.sign(close.diff().fillna(0.0))
    obv = (direction * vol).cumsum()
    win = min(window, len(obv))
    if win < 3:
        return None
    y = obv.iloc[-win:].to_numpy()
    x = np.arange(win)
    slope = float(np.polyfit(x, y, 1)[0])
    scale = float(np.abs(y).mean())
    if scale <= 0:
        return None
    return _round(slope / scale * 100, 2)


def volume_profile(
    df: pd.DataFrame,
    *,
    lookback: int = PROFILE_LOOKBACK,
    bins: int = PROFILE_BINS,
    value_area_pct: float = VALUE_AREA_PCT,
) -> dict[str, Any] | None:
    """Approximate volume profile + POC / Value Area from daily OHLCV.

    Each day's volume is spread uniformly across its High–Low range into ``bins``
    fixed price buckets over the most recent ``lookback`` sessions.
    """
    vol = _clean_volume(df)
    if vol is None:
        return None
    high = pd.to_numeric(df["High"], errors="coerce").reindex(vol.index) if "High" in df else None
    low = pd.to_numeric(df["Low"], errors="coerce").reindex(vol.index) if "Low" in df else None
    close = pd.to_numeric(df["Close"], errors="coerce").reindex(vol.index)
    if high is None or low is None:
        high = low = close

    window = min(lookback, len(vol))
    if window < 10:
        return None
    h = high.iloc[-window:].to_numpy(dtype=float)
    l = low.iloc[-window:].to_numpy(dtype=float)
    v = vol.iloc[-window:].to_numpy(dtype=float)

    lo = float(np.nanmin(l))
    hi = float(np.nanmax(h))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        return None

    edges = np.linspace(lo, hi, bins + 1)
    bin_vol = np.zeros(bins, dtype=float)
    bin_width = (hi - lo) / bins

    for day_high, day_low, day_vol in zip(h, l, v):
        if day_vol <= 0 or not np.isfinite(day_high) or not np.isfinite(day_low):
            continue
        top = max(day_high, day_low)
        bot = min(day_high, day_low)
        if top <= bot:
            # Flat bar: dump all volume into the single containing bin.
            idx = min(bins - 1, max(0, int((bot - lo) / bin_width))) if bin_width > 0 else 0
            bin_vol[idx] += day_vol
            continue
        # Spread the day's volume across the bins its range overlaps, weighted by
        # how much of the bar sits in each bin.
        span = top - bot
        lo_idx = min(bins - 1, max(0, int((bot - lo) / bin_width)))
        hi_idx = min(bins - 1, max(0, int((top - lo) / bin_width)))
        for idx in range(lo_idx, hi_idx + 1):
            overlap = min(top, edges[idx + 1]) - max(bot, edges[idx])
            if overlap > 0:
                bin_vol[idx] += day_vol * (overlap / span)

    total = float(bin_vol.sum())
    if total <= 0:
        return None

    poc_idx = int(np.argmax(bin_vol))
    poc_volume = float(bin_vol[poc_idx])

    # Value Area: expand outward from the POC, always taking the heavier
    # neighbour, until we cover ``value_area_pct`` of total volume.
    target = total * value_area_pct
    lo_i = hi_i = poc_idx
    covered = poc_volume
    while covered < target and (lo_i > 0 or hi_i < bins - 1):
        below = bin_vol[lo_i - 1] if lo_i > 0 else -1.0
        above = bin_vol[hi_i + 1] if hi_i < bins - 1 else -1.0
        if above >= below:
            hi_i += 1
            covered += bin_vol[hi_i]
        else:
            lo_i -= 1
            covered += bin_vol[lo_i]

    def _mid(i: int) -> float:
        return float((edges[i] + edges[i + 1]) / 2)

    profile_bins = [
        {
            "low": _round(float(edges[i]), 2),
            "high": _round(float(edges[i + 1]), 2),
            "mid": _round(_mid(i), 2),
            "volume": int(bin_vol[i]),
            "pctOfPoc": _round(bin_vol[i] / poc_volume * 100, 1) if poc_volume > 0 else None,
        }
        for i in range(bins)
    ]

    price = float(close.iloc[-1]) if not close.isna().all() else None
    return {
        "poc": _round(_mid(poc_idx), 2),
        "vah": _round(float(edges[hi_i + 1]), 2),
        "val": _round(float(edges[lo_i]), 2),
        "valueAreaPct": round(value_area_pct * 100, 1),
        "lookback": window,
        "binCount": bins,
        "rangeLow": _round(lo, 2),
        "rangeHigh": _round(hi, 2),
        "bins": profile_bins,
        "priceNode": volume_at_price(profile_bins, price, poc_volume),
    }


def volume_at_price(
    profile_bins: list[dict[str, Any]],
    price: float | None,
    poc_volume: float | None = None,
) -> dict[str, Any] | None:
    """Classify how much volume has traded at ``price``.

    Returns the bin volume as a % of the POC volume plus a coarse node label so
    callers (Risk/Confluence agents) can tell a high-volume node (strong S/R)
    from a low-volume gap (fast-move risk) — e.g. "a double-bottom at $95 where
    only 30% of POC volume traded" is a weak demand zone.
    """
    if not profile_bins or price is None or not np.isfinite(price):
        return None
    if poc_volume is None:
        poc_volume = max((b["volume"] for b in profile_bins), default=0)
    if not poc_volume:
        return None
    match = None
    for b in profile_bins:
        lo = b.get("low")
        hi = b.get("high")
        if lo is None or hi is None:
            continue
        if lo <= price <= hi:
            match = b
            break
    if match is None:
        # Price sits outside the profiled range entirely (very thin node).
        return {"pctOfPoc": 0.0, "node": "gap", "binVolume": 0}
    pct = match["volume"] / poc_volume * 100 if poc_volume else 0.0
    node = "high" if pct >= 70 else "medium" if pct >= 35 else "low"
    return {"pctOfPoc": _round(pct, 1), "node": node, "binVolume": int(match["volume"])}
