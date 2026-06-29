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

# Neutral/"flat" deadbands for the normalized 21-bar regression slopes. These are
# the single source of truth so the UI badge, the Confluence volume lens and the
# Risk agent all classify accumulation/distribution/neutral identically (they
# import these constants rather than hard-coding their own ±1 cut).
#
# * OBV_FLAT_BAND — % slope below which OBV is "Neutral". Default ±1.0 matches the
#   original Confluence ±1 deadband.
# * PRICE_FLAT_BAND — % slope below which the close trend is "flat". Price slope is
#   normalized by mean |close|, so its magnitude is far smaller than OBV's; a
#   ~2% move over the 21-bar window lands near the ±0.1 default.
OBV_FLAT_BAND = float(os.environ.get("OBV_FLAT_BAND", "1.0"))
PRICE_FLAT_BAND = float(os.environ.get("PRICE_FLAT_BAND", "0.1"))


def _parse_cuts(raw: str | None, default: tuple[float, float, float]) -> tuple[float, float, float]:
    try:
        parts = [float(x) for x in str(raw).split(",")]
    except (ValueError, AttributeError):
        return default
    return (parts[0], parts[1], parts[2]) if len(parts) == 3 else default


# Self-relative OBV strength: percentile cut-offs that map the current |slope|'s
# rank (vs the symbol's own past |slopes|) to {weak, moderate, strong, extreme}.
# Default 33/66/90 → <33 weak, <66 moderate, <90 strong, >=90 extreme.
OBV_STRENGTH_CUTS = _parse_cuts(os.environ.get("OBV_STRENGTH_CUTS", "33,66,90"), (33.0, 66.0, 90.0))
# Minimum rolling slope samples before a percentile/strength is trustworthy.
OBV_STRENGTH_MIN_SAMPLES = max(1, int(os.environ.get("OBV_STRENGTH_MIN_SAMPLES", "30")))

# Exact wording for the four-quadrant price-vs-OBV read (shared so the UI tooltip
# and any agent surface phrase it identically).
_OBV_READINGS = {
    "confirmation_bull": "Confirmation — rally backed by volume, healthy",
    "bearish_divergence": "Bearish divergence — rally on fading participation, suspect",
    "confirmation_bear": "Confirmation — decline backed by selling, healthy downtrend",
    "bullish_divergence": "Bullish divergence — selling into rising accumulation, possible reversal/absorption",
    "neutral": "Inconclusive — price or volume trend too flat to read",
}


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
    price_slope_pct = _price_slope_pct(close)

    price_direction = _direction(price_slope_pct, PRICE_FLAT_BAND)
    obv_label = _obv_label(obv_slope_pct)
    obv_reading = _obv_reading(price_slope_pct, obv_slope_pct)
    obv_pctile, obv_strength, obv_samples = _obv_strength(close, vol, obv_slope_pct)

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
        # Self-relative OBV strength: where the current |slope| ranks vs this
        # symbol's own past |slopes|. ``obvStrength`` is None for a flat OBV or
        # when there isn't enough history (``obvStrengthSamples`` < min).
        "obvSlopePctile": obv_pctile,
        "obvStrength": obv_strength,
        "obvStrengthSamples": obv_samples,
        # Price/OBV four-quadrant read (Part B): the close's own normalized slope,
        # a coarse {Accumulation, Distribution, Neutral} OBV label, the price
        # direction, and the combined divergence/confirmation reading.
        "priceSlopePct": price_slope_pct,
        "priceDirection": price_direction,
        "obvLabel": obv_label,
        "obvReading": obv_reading,
        "state": state,
    }


def _direction(slope_pct: float | None, band: float) -> str:
    """Coarse {up, down, flat} from a normalized slope and its neutral deadband."""
    if slope_pct is None:
        return "flat"
    if slope_pct > band:
        return "up"
    if slope_pct < -band:
        return "down"
    return "flat"


def _obv_label(obv_slope_pct: float | None) -> str:
    """OBV accumulation/distribution/neutral using the shared ``OBV_FLAT_BAND``."""
    direction = _direction(obv_slope_pct, OBV_FLAT_BAND)
    return {"up": "Accumulation", "down": "Distribution", "flat": "Neutral"}[direction]


def _obv_reading(
    price_slope_pct: float | None, obv_slope_pct: float | None
) -> dict[str, str]:
    """Classify the (price direction, OBV direction) pair into the four-quadrant
    read. A flat price OR a neutral OBV is inconclusive; otherwise same-sign is a
    confirmation and opposite-sign is a divergence."""
    price_dir = _direction(price_slope_pct, PRICE_FLAT_BAND)
    obv_dir = _direction(obv_slope_pct, OBV_FLAT_BAND)
    if price_dir == "flat" or obv_dir == "flat":
        kind = "neutral"
    elif price_dir == "up" and obv_dir == "up":
        kind = "confirmation_bull"
    elif price_dir == "up" and obv_dir == "down":
        kind = "bearish_divergence"
    elif price_dir == "down" and obv_dir == "down":
        kind = "confirmation_bear"
    else:  # price down + obv up
        kind = "bullish_divergence"
    return {"kind": kind, "text": _OBV_READINGS[kind]}


def _windowed_slope_pct(y: np.ndarray) -> float | None:
    """Normalized regression slope of one window of values: slope of the best-fit
    line as a % of the window's mean |value| per bar. The single source of truth
    for the OBV slope formula so the point-in-time value and the rolling history
    (and ``risk_service._obv_slope_pct``, kept identical) can't drift."""
    win = len(y)
    if win < 3:
        return None
    slope = float(np.polyfit(np.arange(win), y, 1)[0])
    scale = float(np.abs(y).mean())
    if scale <= 0:
        return None
    return slope / scale * 100


def _obv_series(close: pd.Series, vol: pd.Series) -> "np.ndarray | None":
    """Cumulative signed volume (OBV): +vol on up-closes, −vol on down-closes."""
    close = close.astype(float)
    if close.isna().all() or len(close) < 3:
        return None
    direction = np.sign(close.diff().fillna(0.0))
    return (direction * vol).cumsum().to_numpy()


def _obv_slope_pct(close: pd.Series, vol: pd.Series, window: int = 21) -> float | None:
    """Slope of On-Balance-Volume over ``window`` bars, as % of mean |OBV|.

    Positive = net accumulation, negative = net distribution. Normalising by the
    mean magnitude keeps it comparable across symbols of very different volume.
    """
    obv = _obv_series(close, vol)
    if obv is None:
        return None
    win = min(window, len(obv))
    if win < 3:
        return None
    val = _windowed_slope_pct(obv[-win:])
    return _round(val, 2) if val is not None else None


def _obv_slope_history(close: pd.Series, vol: pd.Series, window: int = 21) -> list[float]:
    """Every full-window OBV slope across the available history (one per bar from
    ``window`` onward), giving the symbol's own past distribution of slope values.
    The last element equals the current ``_obv_slope_pct`` (pre-rounding)."""
    obv = _obv_series(close, vol)
    if obv is None or len(obv) < max(3, window):
        return []
    out: list[float] = []
    for end in range(window, len(obv) + 1):
        val = _windowed_slope_pct(obv[end - window : end])
        if val is not None:
            out.append(val)
    return out


def _strength_label(pctile: float) -> str:
    weak, moderate, strong = OBV_STRENGTH_CUTS
    if pctile < weak:
        return "weak"
    if pctile < moderate:
        return "moderate"
    if pctile < strong:
        return "strong"
    return "extreme"


def _obv_strength(
    close: pd.Series, vol: pd.Series, current_slope: float | None, window: int = 21
) -> tuple[int | None, str | None, int]:
    """Rank the current |slope| against the symbol's own past |slopes|.

    Returns ``(percentile, strength, sampleCount)``. Strength is direction-agnostic
    (the label/sign already convey direction). Guarded: needs at least
    ``OBV_STRENGTH_MIN_SAMPLES`` rolling samples, else ``(None, None, n)``. A flat
    reading (|slope| <= OBV_FLAT_BAND) keeps the percentile but reports no
    strength — calling a flat OBV "weak"/"strong" would mislead."""
    history = _obv_slope_history(close, vol, window)
    samples = len(history)
    if current_slope is None or samples < OBV_STRENGTH_MIN_SAMPLES:
        return None, None, samples
    mags = np.abs(np.asarray(history, dtype=float))
    cur = abs(float(current_slope))
    pctile = int(round(float((mags <= cur).mean()) * 100))
    strength = None if cur <= OBV_FLAT_BAND else _strength_label(pctile)
    return pctile, strength, samples


def _price_slope_pct(close: pd.Series, window: int = 21) -> float | None:
    """Slope of close over ``window`` bars, as % of mean |close| per bar.

    Deliberately mirrors ``_obv_slope_pct``'s window + normalization so the price
    and OBV slopes are directly comparable for the four-quadrant divergence read.
    """
    close = close.astype(float).dropna()
    win = min(window, len(close))
    if win < 3:
        return None
    y = close.iloc[-win:].to_numpy()
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
