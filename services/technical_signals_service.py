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
import threading
from typing import Any

import numpy as np
import pandas as pd

from services.market_cache import CACHE_MISS, TtlCache, make_ticker
from services.risk_service import validate_patterns
from services.volume_service import volume_block, volume_profile

FIB_RATIOS = (0.236, 0.382, 0.5, 0.618, 0.786)
_TIMEFRAMES = (("1M", 21), ("3M", 63), ("6M", 126), ("1Y", 252))

# One daily-history fetch per symbol, shared by both the signal and chart
# builders (and cached so the assessment + Inspector reuse the same series).
_history_ttl = float(os.environ.get("TECHNICAL_SIGNALS_CACHE_TTL_SECONDS", "900"))
_history_max = int(os.environ.get("TECHNICAL_SIGNALS_CACHE_MAX_ENTRIES", "64"))
_history_cache: TtlCache = TtlCache(_history_ttl, _history_max)

# A *failed* history fetch (None/empty) is cached only briefly, not for the full
# success TTL. Otherwise one bad burst -- e.g. a parallel pattern/Fib-map fetch
# colliding with the background sync's yfinance calls -- would freeze a symbol's
# patterns and trend waves blank for 15 min across the whole app (the "view shows
# patterns in the Inspector but the table is empty" symptom). With a short
# cooldown the next request retries and the data fills in. 0 disables the cooldown
# (always retry on the next request).
_history_fail_ttl = float(os.environ.get("TECHNICAL_HISTORY_FAIL_COOLDOWN_SECONDS", "120"))
_history_fail_cache: TtlCache = TtlCache(max(1.0, _history_fail_ttl), 256)

# Cap concurrent yfinance history fetches process-wide. The Fib-map and /patterns
# endpoints each fan out across a ThreadPoolExecutor, and the assessment runs its
# own pool, so without a brake several bursts can hit Yahoo at once (on top of the
# background price sync) and trip rate limiting -- which is what leaves patterns
# and trend waves blank. This semaphore lets the pools keep their width for cache
# hits while serialising the actual network calls to a safe number.
_history_max_concurrency = int(os.environ.get("TECHNICAL_HISTORY_MAX_CONCURRENCY", "3"))
_history_fetch_semaphore = threading.Semaphore(max(1, _history_max_concurrency))


class TechnicalSignalsService:
    def __init__(self) -> None:
        # Defensive: strip any stray inline `# comment` / whitespace so a
        # mis-parsed .env value (e.g. injected verbatim by the editor's debugger)
        # can't reach yfinance as an invalid period like "2y  # ...".
        raw_period = os.environ.get("TECHNICAL_SIGNALS_PERIOD", "2y")
        self.period = (raw_period.split("#", 1)[0].strip() or "2y")
        # Pivot (zig-zag) reversal threshold. 0 = adaptive from ATR%.
        self.pivot_pct = float(os.environ.get("TECHNICAL_PIVOT_PCT", "0"))
        self.pivot_atr_mult = float(os.environ.get("TECHNICAL_PIVOT_ATR_MULT", "2.5"))
        self.pivot_min_pct = float(os.environ.get("TECHNICAL_PIVOT_MIN_PCT", "4"))
        self.pivot_max_pct = float(os.environ.get("TECHNICAL_PIVOT_MAX_PCT", "18"))
        self.max_waves = int(os.environ.get("TECHNICAL_MAX_WAVES", "6"))
        # Tier 3: named chart-pattern detection over the pivot sequence.
        self.detect_patterns = os.environ.get("ASSESSMENT_PATTERNS", "1").lower() not in (
            "0",
            "false",
            "no",
            "off",
        )
        # Tolerance for "similar" pivots (e.g. the two tops of a double top).
        self.pattern_tol_pct = float(os.environ.get("TECHNICAL_PATTERN_TOL_PCT", "3"))

    def _pivot_kwargs(self) -> dict[str, float]:
        return {
            "pivot_pct": self.pivot_pct,
            "pivot_atr_mult": self.pivot_atr_mult,
            "pivot_min_pct": self.pivot_min_pct,
            "pivot_max_pct": self.pivot_max_pct,
            "pattern_tol_pct": self.pattern_tol_pct if self.detect_patterns else 0.0,
        }

    def _history(self, symbol: str) -> "pd.DataFrame | None":
        key = (symbol.upper(), self.period)
        cached = _history_cache.peek(key)
        if cached is not CACHE_MISS:
            return cached
        if _history_fail_ttl > 0 and _history_fail_cache.peek(key) is not CACHE_MISS:
            return None  # recently failed; cool down before retrying
        with _history_fetch_semaphore:
            # Re-check after waiting: another thread may have filled (or failed)
            # this symbol while we queued behind the concurrency limit.
            cached = _history_cache.peek(key)
            if cached is not CACHE_MISS:
                return cached
            if _history_fail_ttl > 0 and _history_fail_cache.peek(key) is not CACHE_MISS:
                return None
            try:
                history = make_ticker(symbol).history(period=self.period, auto_adjust=True)
            except Exception:  # noqa: BLE001 - network/parse issues are non-fatal
                history = None
            if history is not None and getattr(history, "empty", True):
                history = None
            if history is None:
                # A failure often means this thread's Yahoo session went stale
                # (expired cookie/crumb). Drop it so the next call rebuilds a
                # fresh one instead of reusing the dead session forever.
                from services.market_cache import reset_yf_session

                reset_yf_session()
                # Brief negative cache so a transient failure doesn't hammer Yahoo
                # but also doesn't freeze the symbol blank for the full success TTL.
                if _history_fail_ttl > 0:
                    _history_fail_cache.put(key, True)
            else:
                _history_cache.put(key, history)
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
        _history_fail_cache.clear()

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
        pattern_tol_pct: float = 3.0,
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
        prices = [float(v) for v in close.to_numpy()]
        dates = [d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d) for d in close.index]
        pivots = _zigzag(prices, threshold)
        signals["swing"] = _swing_block(close, price, threshold, pivots=pivots)
        # Volume context rides the same DataFrame (Volume was previously discarded).
        profile = volume_profile(df)
        signals["volume"] = volume_block(df)
        signals["volumeProfile"] = profile
        detected = (
            _detect_patterns(prices, dates, pivots, price, pattern_tol_pct)
            if pattern_tol_pct > 0
            else []
        )
        # Risk agent: validate each pattern against volume (Phase 2).
        signals["patterns"] = validate_patterns(detected, df, profile, price)
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
        pattern_tol_pct: float = 3.0,
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
        vol_series = (
            pd.to_numeric(df["Volume"], errors="coerce").reindex(close.index).fillna(0.0)
            if "Volume" in df
            else None
        )
        points = [
            {
                "date": dates[j],
                "price": round(prices[j], 2),
                **({"volume": int(vol_series.iloc[j])} if vol_series is not None else {}),
            }
            for j in range(first_idx, len(prices))
        ]
        timeline = {
            "windowStart": dates[first_idx][:7],
            "windowEnd": dates[-1][:7],
            "startDate": dates[first_idx],
            "endDate": dates[-1],
            "points": points,
        }

        swing = _swing_block(close, price, threshold, pivots=pivots)
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
        profile = volume_profile(df)
        detected = (
            _detect_patterns(prices, dates, pivots, price, pattern_tol_pct)
            if pattern_tol_pct > 0
            else []
        )
        patterns = validate_patterns(detected, df, profile, price)
        return {
            "trendWaves": waves,
            "chartTimeline": timeline,
            "fib": fib,
            "swing": swing,
            "patterns": patterns,
            "volume": volume_block(df),
            "volumeProfile": profile,
        }


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


def _swing_block(
    close: pd.Series,
    price: float,
    threshold: float,
    pivots: list[tuple[int, str]] | None = None,
) -> dict[str, Any] | None:
    prices = [float(v) for v in close.to_numpy()]
    dates = [d.strftime("%Y-%m-%d") if hasattr(d, "strftime") else str(d) for d in close.index]
    if pivots is None:
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


# --------------------------------------------------------------------------- #
# Tier 3 — named chart-pattern detection over the pivot sequence.
#
# Deterministic, geometry-based matchers on the same adaptive zig-zag pivots the
# trend/swing logic uses. Each match carries a confidence and key levels so the
# LLM and rules engine can weigh it as ONE probabilistic input, never gospel —
# classic patterns are subjective and have mixed predictive power.
# --------------------------------------------------------------------------- #
def _similar(a: float, b: float, tol: float) -> bool:
    base = (abs(a) + abs(b)) / 2
    return base > 0 and abs(a - b) / base <= tol


def _closeness(a: float, b: float) -> float:
    """1.0 when identical, decaying toward 0 as they diverge."""
    base = (abs(a) + abs(b)) / 2
    if base <= 0:
        return 0.0
    return max(0.0, 1 - abs(a - b) / base)


def _pattern_conf(base: float, closeness: float) -> float:
    return round(min(0.95, base + 0.35 * closeness), 2)


def _points(
    w: list[tuple[int, str, float]], dates: list[str], roles: list[str] | None = None
) -> list[dict[str, Any]]:
    """The pivot vertices that define a pattern, for drawing it on the chart."""
    out = []
    for k, (i, _t, p) in enumerate(w):
        role = roles[k] if roles and k < len(roles) else _t
        out.append({"date": dates[i], "price": round(p, 2), "role": role})
    return out


def _pattern(
    name: str,
    ptype: str,
    confidence: float,
    status: str,
    start: str,
    end: str,
    key_label: str,
    key_price: float,
    target: float | None,
    price: float,
    points: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    tgt = f", measured target ≈ ${target}" if target else ""
    return {
        "name": name,
        "type": ptype,
        "confidence": confidence,
        "status": status,
        "startDate": start,
        "endDate": end,
        "keyLevel": {"label": key_label, "price": key_price},
        "target": target,
        "points": points or [],
        "summary": f"{name} ({ptype}, {status}); {key_label} ${key_price}{tgt}",
    }


def _flat(vals: list[float], tol: float) -> bool:
    avg = sum(vals) / len(vals)
    return avg > 0 and (max(vals) - min(vals)) / avg <= tol


def _strictly_rising(vals: list[float]) -> bool:
    return len(vals) >= 2 and all(b > a for a, b in zip(vals, vals[1:]))


def _strictly_falling(vals: list[float]) -> bool:
    return len(vals) >= 2 and all(b < a for a, b in zip(vals, vals[1:]))


def _detect_triangle(
    window: list[tuple[int, str, float]], price: float, tol: float, dates: list[str]
) -> dict[str, Any] | None:
    highs = [p for _, t, p in window if t == "high"]
    lows = [p for _, t, p in window if t == "low"]
    if len(highs) < 2 or len(lows) < 2:
        return None
    flat_high = _flat(highs, tol)
    flat_low = _flat(lows, tol)
    rising_low = _strictly_rising(lows) and lows[-1] > lows[0] * (1 + tol)
    falling_high = _strictly_falling(highs) and highs[-1] < highs[0] * (1 - tol)
    start, end = dates[window[0][0]], dates[window[-1][0]]

    # Triangles need the flat side touched >=3 times so they aren't confused with
    # a 2-touch double top/bottom.
    pts = _points(window, dates)
    if flat_high and rising_low and len(highs) >= 3:
        return _pattern(
            "Ascending Triangle", "bullish", _pattern_conf(0.5, 1 - (max(highs) - min(highs)) / max(highs)),
            "confirmed" if price > max(highs) else "forming", start, end,
            "resistance", round(sum(highs) / len(highs), 2), None, price, pts,
        )
    if flat_low and falling_high and len(lows) >= 3:
        return _pattern(
            "Descending Triangle", "bearish", _pattern_conf(0.5, 1 - (max(lows) - min(lows)) / max(lows)),
            "confirmed" if price < min(lows) else "forming", start, end,
            "support", round(sum(lows) / len(lows), 2), None, price, pts,
        )
    if falling_high and rising_low and len(highs) >= 2 and len(lows) >= 2:
        return _pattern(
            "Symmetrical Triangle", "neutral", 0.5, "forming", start, end,
            "apex", round((highs[-1] + lows[-1]) / 2, 2), None, price, pts,
        )
    return None


def _windows(
    pts: list[tuple[int, str, float]], length: int, lookback: int
) -> list[list[tuple[int, str, float]]]:
    """Sub-windows of ``length`` within the last ``lookback`` pivots, most recent
    first. The zig-zag always appends a tentative trailing pivot, so a completed
    pattern usually sits one or two pivots back from the tail — scanning recent
    windows (not just ``pts[-length:]``) is what makes detection reliable."""
    n = len(pts)
    if n < length:
        return []
    max_start = n - length
    min_start = max(0, n - lookback)
    return [pts[s:s + length] for s in range(max_start, min_start - 1, -1)]


def _match_hs(
    w: list[tuple[int, str, float]], price: float, tol: float, dates: list[str]
) -> dict[str, Any] | None:
    types = [t for _, t, _ in w]
    p0, p1, p2, p3, p4 = (p for _, _, p in w)
    if types == ["high", "low", "high", "low", "high"]:
        ls, t1, head, t2, rs = p0, p1, p2, p3, p4
        if head > ls and head > rs and _similar(ls, rs, tol * 2):
            neckline = (t1 + t2) / 2
            roles = ["Left Shoulder", "Trough", "Head", "Trough", "Right Shoulder"]
            return _pattern(
                "Head & Shoulders", "bearish", _pattern_conf(0.6, _closeness(ls, rs)),
                "confirmed" if price < neckline else "forming",
                dates[w[0][0]], dates[w[-1][0]], "neckline", round(neckline, 2),
                round(neckline - (head - neckline), 2), price, _points(w, dates, roles),
            )
    elif types == ["low", "high", "low", "high", "low"]:
        ls, t1, head, t2, rs = p0, p1, p2, p3, p4
        if head < ls and head < rs and _similar(ls, rs, tol * 2):
            neckline = (t1 + t2) / 2
            roles = ["Left Shoulder", "Peak", "Head", "Peak", "Right Shoulder"]
            return _pattern(
                "Inverse Head & Shoulders", "bullish", _pattern_conf(0.6, _closeness(ls, rs)),
                "confirmed" if price > neckline else "forming",
                dates[w[0][0]], dates[w[-1][0]], "neckline", round(neckline, 2),
                round(neckline + (neckline - head), 2), price, _points(w, dates, roles),
            )
    return None


def _match_double(
    w: list[tuple[int, str, float]], price: float, tol: float, dates: list[str]
) -> dict[str, Any] | None:
    types = [t for _, t, _ in w]
    a, mid, b = (p for _, _, p in w)
    if types == ["high", "low", "high"] and _similar(a, b, tol):
        return _pattern(
            "Double Top", "bearish", _pattern_conf(0.55, _closeness(a, b)),
            "confirmed" if price < mid else "forming",
            dates[w[0][0]], dates[w[-1][0]], "neckline", round(mid, 2),
            round(mid - (max(a, b) - mid), 2), price,
            _points(w, dates, ["Top", "Neckline", "Top"]),
        )
    if types == ["low", "high", "low"] and _similar(a, b, tol):
        return _pattern(
            "Double Bottom", "bullish", _pattern_conf(0.55, _closeness(a, b)),
            "confirmed" if price > mid else "forming",
            dates[w[0][0]], dates[w[-1][0]], "neckline", round(mid, 2),
            round(mid + (mid - min(a, b)), 2), price,
            _points(w, dates, ["Bottom", "Neckline", "Bottom"]),
        )
    return None


def _detect_patterns(
    prices: list[float],
    dates: list[str],
    pivots: list[tuple[int, str]],
    price: float,
    tol_pct: float = 3.0,
    max_patterns: int = 3,
) -> list[dict[str, Any]]:
    if len(pivots) < 3 or tol_pct <= 0:
        return []
    tol = max(0.005, tol_pct / 100.0)
    pts = [(i, t, prices[i]) for i, t in pivots]

    # Return a single, non-contradictory best read of the current structure
    # rather than several overlapping labels on the same pivots (a Head &
    # Shoulders trivially contains an inner "double bottom"; an ascending
    # triangle's flat highs look like a "double top"). Priority by structural
    # completeness: H&S (5 pivots) > triangle (4) vs double (3) disambiguated.

    # 1) Head & Shoulders — strongest, uses 5 pivots.
    for w in _windows(pts, 5, lookback=6):
        hs = _match_hs(w, price, tol, dates)
        if hs:
            return [hs]

    # 2) Triangle (>=3 flat-side touches) vs Double (3 pivots).
    triangle = _detect_triangle(pts[-7:], price, tol, dates)
    double = None
    for w in _windows(pts, 3, lookback=5):
        double = _match_double(w, price, tol, dates)
        if double:
            break

    # A triangle explains the flat side better than a double would, so it wins
    # when both fire on the same swing.
    if triangle:
        return [triangle]
    if double:
        return [double]
    return []
