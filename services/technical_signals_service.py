"""Self-contained technical signals computed from price history.

Tier 2 of the assessment-accuracy work: instead of relying solely on externally
imported trend/Fibonacci snapshots (which are anchored to hand-picked, per-symbol
windows), this service derives indicators and an *adaptive* swing structure
directly from ~2 years of daily history that we fetch and cache.

Two ideas keep it from collapsing into a single misleading window:

* **Multi-timeframe** — trend/return is summarised over 1M/3M/6M/1Y so the
  assessment can reason "short-term pullback within a long-term uptrend".
* **Adaptive anchoring** — the Fibonacci swing is anchored to the dominant
  recent swing detected by a volatility-scaled zig-zag, not a fixed calendar
  window, reproducing per-symbol relevance automatically.

Only pandas/numpy are used (no TA-Lib/scipy) to keep the Render memory
footprint small. ``compute_signals(df)`` is pure so the math is unit-testable
without the network; ``get_signals(symbol)`` adds fetching + TTL caching.
"""
from __future__ import annotations

import os
from typing import Any

import numpy as np
import pandas as pd

from services.market_cache import CACHE_MISS, TtlCache, make_ticker

FIB_RATIOS = (0.236, 0.382, 0.5, 0.618, 0.786)
_TIMEFRAMES = (("1M", 21), ("3M", 63), ("6M", 126), ("1Y", 252))

# One daily-history fetch per symbol, shared by both the signal and chart
# builders (and cached so the assessment + Inspector reuse the same series).
_history_ttl = float(os.environ.get("TECHNICAL_SIGNALS_CACHE_TTL_SECONDS", "900"))
_history_max = int(os.environ.get("TECHNICAL_SIGNALS_CACHE_MAX_ENTRIES", "64"))
_history_cache: TtlCache = TtlCache(_history_ttl, _history_max)


class TechnicalSignalsService:
    def __init__(self) -> None:
        self.period = os.environ.get("TECHNICAL_SIGNALS_PERIOD", "2y")
        # Pivot (zig-zag) reversal threshold. 0 = adaptive from ATR%.
        self.pivot_pct = float(os.environ.get("TECHNICAL_PIVOT_PCT", "0"))
        self.pivot_atr_mult = float(os.environ.get("TECHNICAL_PIVOT_ATR_MULT", "2.5"))
        self.pivot_min_pct = float(os.environ.get("TECHNICAL_PIVOT_MIN_PCT", "4"))
        self.pivot_max_pct = float(os.environ.get("TECHNICAL_PIVOT_MAX_PCT", "18"))
        self.max_waves = int(os.environ.get("TECHNICAL_MAX_WAVES", "6"))

    def _pivot_kwargs(self) -> dict[str, float]:
        return {
            "pivot_pct": self.pivot_pct,
            "pivot_atr_mult": self.pivot_atr_mult,
            "pivot_min_pct": self.pivot_min_pct,
            "pivot_max_pct": self.pivot_max_pct,
        }

    def _history(self, symbol: str) -> "pd.DataFrame | None":
        key = (symbol.upper(), self.period)
        cached = _history_cache.peek(key)
        if cached is not CACHE_MISS:
            return cached
        try:
            history = make_ticker(symbol).history(period=self.period, auto_adjust=True)
        except Exception:  # noqa: BLE001 - network/parse issues are non-fatal
            history = None
        if history is not None and getattr(history, "empty", True):
            history = None
        _history_cache.put(key, history)  # cache misses too, to avoid hammering
        return history

    def get_signals(self, symbol: str) -> dict[str, Any] | None:
        df = self._history(symbol)
        if df is None:
            return None
        return self.compute_signals(df, symbol=symbol, period=self.period, **self._pivot_kwargs())

    def get_chart(self, symbol: str) -> dict[str, Any] | None:
        """Trend-wave legs + price timeline + adaptive Fibonacci for the Inspector,
        derived from the same cached history the assessment signals use."""
        df = self._history(symbol)
        if df is None:
            return None
        return self.compute_chart(
            df, symbol=symbol, period=self.period, max_waves=self.max_waves, **self._pivot_kwargs()
        )

    @staticmethod
    def clear_cache() -> None:
        _history_cache.clear()

    # ------------------------------------------------------------------ #
    # Pure computation (no network) — safe to unit test with a synthetic df
    # ------------------------------------------------------------------ #
    @staticmethod
    def compute_signals(
        df: pd.DataFrame,
        *,
        symbol: str = "",
        period: str = "2y",
        pivot_pct: float = 0.0,
        pivot_atr_mult: float = 2.5,
        pivot_min_pct: float = 4.0,
        pivot_max_pct: float = 18.0,
    ) -> dict[str, Any] | None:
        if df is None or df.empty or "Close" not in df:
            return None
        close = df["Close"].astype(float).dropna()
        if len(close) < 30:
            return None
        high = df["High"].astype(float).reindex(close.index) if "High" in df else close
        low = df["Low"].astype(float).reindex(close.index) if "Low" in df else close
        price = float(close.iloc[-1])
        if price <= 0:
            return None

        as_of = close.index[-1]
        as_of_str = as_of.strftime("%Y-%m-%d") if hasattr(as_of, "strftime") else str(as_of)

        atr14 = _atr(high, low, close, 14)
        atr_pct = round(atr14 / price * 100, 2) if atr14 else None

        signals: dict[str, Any] = {
            "symbol": symbol.upper(),
            "asOf": as_of_str,
            "period": period,
            "price": round(price, 2),
            "trend": _trend_block(close, price),
            "momentum": _momentum_block(close),
            "volatility": {"atr14": _round(atr14), "atrPct": atr_pct},
            "range52w": _range_block(high, low, price),
            "returns": _returns_block(close),
            "timeframes": _timeframes_block(close),
        }

        threshold = pivot_pct if pivot_pct > 0 else _adaptive_threshold(
            atr_pct, pivot_atr_mult, pivot_min_pct, pivot_max_pct
        )
        signals["swing"] = _swing_block(close, price, threshold)
        return signals

    @staticmethod
    def compute_chart(
        df: pd.DataFrame,
        *,
        symbol: str = "",
        period: str = "2y",
        pivot_pct: float = 0.0,
        pivot_atr_mult: float = 2.5,
        pivot_min_pct: float = 4.0,
        pivot_max_pct: float = 18.0,
        max_waves: int = 6,
    ) -> dict[str, Any] | None:
        """Build Inspector-shaped trend waves + price timeline + Fibonacci from
        the detected zig-zag pivots. Shapes mirror TechnicalService so the
        frontend renders computed and imported sources identically."""
        if df is None or getattr(df, "empty", True) or "Close" not in df:
            return None
        close = df["Close"].astype(float).dropna()
        if len(close) < 30:
            return None
        high = df["High"].astype(float).reindex(close.index) if "High" in df else close
        low = df["Low"].astype(float).reindex(close.index) if "Low" in df else close
        price = float(close.iloc[-1])
        if price <= 0:
            return None

        atr14 = _atr(high, low, close, 14)
        atr_pct = atr14 / price * 100 if atr14 else None
        threshold = pivot_pct if pivot_pct > 0 else _adaptive_threshold(
            atr_pct, pivot_atr_mult, pivot_min_pct, pivot_max_pct
        )

        prices = [float(v) for v in close.to_numpy()]
        dates = [d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d) for d in close.index]
        pivots = _zigzag(prices, threshold)
        if len(pivots) < 2:
            return None

        selected = pivots[-(max_waves + 1):]
        waves: list[dict[str, Any]] = []
        for n in range(len(selected) - 1):
            i0 = selected[n][0]
            i1 = selected[n + 1][0]
            ps, pe = prices[i0], prices[i1]
            direction = "up" if pe >= ps else "down"
            leg = "Low → Peak (Bullish)" if direction == "up" else "Peak → Low (Bearish)"
            waves.append(
                {
                    "label": f"T{n + 1}",
                    "type": "Bullish" if direction == "up" else "Bearish",
                    "direction": direction,
                    "startDate": dates[i0],
                    "endDate": dates[i1],
                    "priceStart": round(ps, 2),
                    "priceEnd": round(pe, 2),
                    "movePct": round((pe / ps - 1) * 100, 2) if ps else None,
                    "legPattern": leg,
                    "legSummary": f"From {dates[i0]} until {dates[i1]} · {leg}",
                    "displayLow": round(min(ps, pe), 2),
                    "displayHigh": round(max(ps, pe), 2),
                }
            )

        first_idx = selected[0][0]
        points = [
            {"date": dates[j], "price": round(prices[j], 2)} for j in range(first_idx, len(prices))
        ]
        timeline = {
            "windowStart": dates[first_idx][:7],
            "windowEnd": dates[-1][:7],
            "startDate": dates[first_idx],
            "endDate": dates[-1],
            "points": points,
        }

        swing = _swing_block(close, price, threshold)
        fib = None
        if swing:
            fib = {
                "symbol": symbol.upper(),
                "period": f"{timeline['windowStart']} → {timeline['windowEnd']}",
                "swingHigh": swing["swingHigh"],
                "swingLow": swing["swingLow"],
                "levels": swing["levels"],
                "anchorTrend": f"Computed swing · {swing['structure']}",
                "source": "computed",
            }
        return {"trendWaves": waves, "chartTimeline": timeline, "fib": fib, "swing": swing}


# --------------------------------------------------------------------------- #
# Indicator helpers
# --------------------------------------------------------------------------- #
def _round(value: float | None, ndigits: int = 2) -> float | None:
    if value is None or (isinstance(value, float) and (np.isnan(value) or np.isinf(value))):
        return None
    return round(float(value), ndigits)


def _sma(series: pd.Series, window: int) -> float | None:
    if len(series) < window:
        return None
    return float(series.rolling(window).mean().iloc[-1])


def _trend_block(close: pd.Series, price: float) -> dict[str, Any]:
    sma20 = _sma(close, 20)
    sma50 = _sma(close, 50)
    sma200 = _sma(close, 200)

    ma_stack = None
    if sma20 and sma50 and sma200:
        if sma20 > sma50 > sma200:
            ma_stack = "bullish"
        elif sma20 < sma50 < sma200:
            ma_stack = "bearish"
        else:
            ma_stack = "mixed"

    cross_state = _cross_state(close)

    slope_pct_yr = None
    window = min(63, len(close))
    if window >= 10:
        y = close.iloc[-window:].to_numpy()
        x = np.arange(window)
        slope = float(np.polyfit(x, y, 1)[0])
        mean = float(y.mean())
        if mean:
            slope_pct_yr = round(slope / mean * 252 * 100, 1)

    return {
        "sma20": _round(sma20),
        "sma50": _round(sma50),
        "sma200": _round(sma200),
        "priceVsSma50Pct": _round((price / sma50 - 1) * 100) if sma50 else None,
        "priceVsSma200Pct": _round((price / sma200 - 1) * 100) if sma200 else None,
        "maStack": ma_stack,
        "crossState": cross_state,
        "slopePctPerYr": slope_pct_yr,
    }


def _cross_state(close: pd.Series) -> str | None:
    if len(close) < 200:
        return None
    sma50 = close.rolling(50).mean()
    sma200 = close.rolling(200).mean()
    now = sma50.iloc[-1] - sma200.iloc[-1]
    lookback = min(10, len(close) - 201) if len(close) > 201 else 1
    prev = sma50.iloc[-1 - lookback] - sma200.iloc[-1 - lookback]
    if np.isnan(now) or np.isnan(prev):
        return None
    if prev <= 0 < now:
        return "golden"
    if prev >= 0 > now:
        return "death"
    return "above" if now > 0 else "below"


def _momentum_block(close: pd.Series) -> dict[str, Any]:
    rsi = _rsi(close, 14)
    zone = None
    if rsi is not None:
        zone = "overbought" if rsi >= 70 else "oversold" if rsi <= 30 else "neutral"

    macd = _macd(close)
    return {"rsi14": _round(rsi, 1), "rsiZone": zone, "macd": macd}


def _rsi(close: pd.Series, period: int = 14) -> float | None:
    if len(close) < period + 1:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    last_gain = float(avg_gain.iloc[-1])
    last_loss = float(avg_loss.iloc[-1])
    if last_loss == 0:
        return 100.0
    rs = last_gain / last_loss
    return 100 - 100 / (1 + rs)


def _macd(close: pd.Series) -> dict[str, Any] | None:
    if len(close) < 35:
        return None
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal = macd_line.ewm(span=9, adjust=False).mean()
    line = float(macd_line.iloc[-1])
    sig = float(signal.iloc[-1])
    hist = line - sig
    return {
        "line": _round(line, 3),
        "signal": _round(sig, 3),
        "hist": _round(hist, 3),
        "state": "bullish" if hist >= 0 else "bearish",
    }


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float | None:
    if len(close) < period + 1:
        return None
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    value = float(atr.iloc[-1])
    return value if not np.isnan(value) else None


def _range_block(high: pd.Series, low: pd.Series, price: float) -> dict[str, Any]:
    window = min(252, len(high))
    hi = float(high.iloc[-window:].max())
    lo = float(low.iloc[-window:].min())
    position = None
    if hi > lo:
        position = round((price - lo) / (hi - lo) * 100, 1)
    return {
        "high": _round(hi),
        "low": _round(lo),
        "positionPct": position,
        "pctFromHigh": _round((price / hi - 1) * 100) if hi else None,
        "pctFromLow": _round((price / lo - 1) * 100) if lo else None,
    }


def _returns_block(close: pd.Series) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for label, days in _TIMEFRAMES:
        if len(close) > days:
            ref = float(close.iloc[-(days + 1)])
            out[label] = _round((close.iloc[-1] / ref - 1) * 100) if ref else None
        else:
            out[label] = None
    return out


def _timeframes_block(close: pd.Series) -> list[dict[str, Any]]:
    frames = []
    for label, days in _TIMEFRAMES:
        if len(close) <= days:
            continue
        ref = float(close.iloc[-(days + 1)])
        if not ref:
            continue
        ret = (close.iloc[-1] / ref - 1) * 100
        direction = "up" if ret > 3 else "down" if ret < -3 else "flat"
        frames.append({"window": label, "return": round(ret, 2), "direction": direction})
    return frames


def _adaptive_threshold(
    atr_pct: float | None, mult: float, min_pct: float, max_pct: float
) -> float:
    if not atr_pct:
        return max(min_pct, 6.0)
    return float(min(max_pct, max(min_pct, round(atr_pct * mult, 2))))


def _zigzag(prices: list[float], pct: float) -> list[tuple[int, str]]:
    """Return alternating (index, 'high'|'low') pivots using a % reversal filter.

    The final running extreme is appended as a tentative pivot so the current
    leg is always represented.
    """
    n = len(prices)
    if n < 3 or pct <= 0:
        return []
    pivots: list[tuple[int, str]] = []
    ref_idx, ref_price = 0, prices[0]
    ext_idx, ext_price = 0, prices[0]
    direction = 0  # 0 unknown, 1 up, -1 down

    for i in range(1, n):
        p = prices[i]
        if direction == 0:
            if (p - ref_price) / ref_price * 100 >= pct:
                pivots.append((ref_idx, "low"))
                direction, ext_idx, ext_price = 1, i, p
            elif (ref_price - p) / ref_price * 100 >= pct:
                pivots.append((ref_idx, "high"))
                direction, ext_idx, ext_price = -1, i, p
        elif direction == 1:
            if p > ext_price:
                ext_idx, ext_price = i, p
            elif (ext_price - p) / ext_price * 100 >= pct:
                pivots.append((ext_idx, "high"))
                direction, ext_idx, ext_price = -1, i, p
        else:  # direction == -1
            if p < ext_price:
                ext_idx, ext_price = i, p
            elif (p - ext_price) / ext_price * 100 >= pct:
                pivots.append((ext_idx, "low"))
                direction, ext_idx, ext_price = 1, i, p

    if direction == 1:
        pivots.append((ext_idx, "high"))
    elif direction == -1:
        pivots.append((ext_idx, "low"))
    return pivots


def _swing_block(close: pd.Series, price: float, threshold: float) -> dict[str, Any] | None:
    prices = [float(v) for v in close.to_numpy()]
    dates = [d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d) for d in close.index]
    pivots = _zigzag(prices, threshold)
    if len(pivots) < 2:
        return None

    highs = [(i, t) for i, t in pivots if t == "high"]
    lows = [(i, t) for i, t in pivots if t == "low"]
    if not highs or not lows:
        return None

    last_high_idx = highs[-1][0]
    last_low_idx = lows[-1][0]
    swing_high = prices[last_high_idx]
    swing_low = prices[last_low_idx]
    if swing_high <= swing_low:
        return None

    last_idx, last_type = pivots[-1]
    leg_direction = "up" if last_type == "high" else "down"
    structure = _structure(highs, lows, prices)

    span = swing_high - swing_low
    levels = [
        {"label": f"{ratio * 100:.1f}%", "ratio": ratio, "price": round(swing_high - span * ratio, 2)}
        for ratio in FIB_RATIOS
    ]
    nearest = min(
        levels, key=lambda lvl: abs(price - lvl["price"]) if lvl["price"] else float("inf")
    )
    nearest_level = {
        "label": nearest["label"],
        "price": nearest["price"],
        "distancePct": round(abs(price - nearest["price"]) / price * 100, 2),
    }

    recent_pivots = [
        {"date": dates[i], "price": round(prices[i], 2), "type": t} for i, t in pivots[-5:]
    ]
    return {
        "source": "computed",
        "thresholdPct": round(threshold, 2),
        "swingHigh": round(swing_high, 2),
        "swingLow": round(swing_low, 2),
        "swingHighDate": dates[last_high_idx],
        "swingLowDate": dates[last_low_idx],
        "legDirection": leg_direction,
        "structure": structure,
        "levels": levels,
        "nearestLevel": nearest_level,
        "pivots": recent_pivots,
    }


def _structure(
    highs: list[tuple[int, str]], lows: list[tuple[int, str]], prices: list[float]
) -> str:
    higher_highs = lower_highs = higher_lows = lower_lows = False
    if len(highs) >= 2:
        higher_highs = prices[highs[-1][0]] > prices[highs[-2][0]]
        lower_highs = prices[highs[-1][0]] < prices[highs[-2][0]]
    if len(lows) >= 2:
        higher_lows = prices[lows[-1][0]] > prices[lows[-2][0]]
        lower_lows = prices[lows[-1][0]] < prices[lows[-2][0]]
    if higher_highs and higher_lows:
        return "uptrend (higher highs & higher lows)"
    if lower_highs and lower_lows:
        return "downtrend (lower highs & lower lows)"
    if higher_lows and not higher_highs:
        return "rising lows (potential accumulation)"
    if lower_highs and not lower_lows:
        return "falling highs (potential distribution)"
    return "range / mixed"
