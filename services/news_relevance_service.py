"""Phase 1 news-relevance scoring via a daily event study.

Relevance = how strongly the market *reacted* to an article. For each news item
we measure the stock's return on the news's trading day, strip out the market's
move (beta-adjusted vs an index), standardize it by the stock's own normal daily
volatility (so a 3% move on a calm name outranks 3% on a jumpy one), and boost it
when volume confirms the move. The result is a 0-100 relevance score; the Summary
feed is then ranked by relevance blended with recency.

This tier uses daily bars only, so it works for any article inside the history
window. Intraday precision (exact minutes after publication) is a future phase.
"""
from __future__ import annotations

import math
import os
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from services.market_cache import TtlCache, make_ticker, yf_throttle

INDEX_SYMBOL = os.environ.get("NEWS_RELEVANCE_INDEX", "SPY").upper()
HISTORY_PERIOD = os.environ.get("NEWS_RELEVANCE_HISTORY_PERIOD", "6mo")
VOL_LOOKBACK = max(5, int(os.environ.get("NEWS_RELEVANCE_VOL_LOOKBACK", "30")))
# A ~2 sigma abnormal move saturates the magnitude term toward its max.
Z_REF = max(0.1, float(os.environ.get("NEWS_RELEVANCE_Z_REF", "2.0")))
RECENCY_HALFLIFE_DAYS = max(0.5, float(os.environ.get("NEWS_RELEVANCE_HALFLIFE_DAYS", "5")))
_CACHE_TTL = float(os.environ.get("NEWS_RELEVANCE_CACHE_TTL_SECONDS", "900"))


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# --- News-derived sentiment (Phase 1) ---------------------------------------
# An article only counts toward sentiment if the market reacted to it at least
# this strongly (relevanceScore is 0-100, already recency-weighted).
NEWS_SENTIMENT_MIN_RELEVANCE = _env_int("NEWS_SENTIMENT_MIN_RELEVANCE", 25)
# |net| at or beyond this band flips the label off "neutral".
NEWS_SENTIMENT_BAND = _env_float("NEWS_SENTIMENT_BAND", 0.20)

_PRICE_CACHE = TtlCache(ttl_seconds=_CACHE_TTL, max_entries=8)

# --- Phase 2: on-demand, per-symbol intraday deep dive -----------------------
# Yahoo only serves ~7-8 days of 1-minute bars, so the intraday tier only covers
# very recent articles; older ones fall back to the Phase 1 daily score.
INTRADAY_PERIOD = os.environ.get("NEWS_RELEVANCE_INTRADAY_PERIOD", "7d")
INTRADAY_INTERVAL = os.environ.get("NEWS_RELEVANCE_INTRADAY_INTERVAL", "1m")
REACTION_WINDOW_MINUTES = max(
    1, int(os.environ.get("NEWS_RELEVANCE_REACTION_WINDOW_MINUTES", "30"))
)
# Don't even attempt intraday for articles older than this (1m data won't exist).
INTRADAY_MAX_AGE_DAYS = max(
    1.0, float(os.environ.get("NEWS_RELEVANCE_INTRADAY_MAX_AGE_DAYS", "10"))
)
_INTRADAY_CACHE_TTL = float(
    os.environ.get("NEWS_RELEVANCE_INTRADAY_CACHE_TTL_SECONDS", "900")
)
_INTRADAY_CACHE = TtlCache(ttl_seconds=_INTRADAY_CACHE_TTL, max_entries=16)


def _parse_dt(value: Any) -> datetime | None:
    """Best-effort parse of a news 'published' field into an aware datetime."""
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    iso = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%a, %d %b %Y %H:%M:%S %z"):
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                dt = None
        if dt is None:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _bulk_history(symbols: tuple[str, ...]) -> pd.DataFrame | None:
    """One throttled, cached bulk download of daily OHLCV for all symbols."""
    if not symbols:
        return None

    def fetch() -> pd.DataFrame | None:
        import yfinance as yf

        try:
            with yf_throttle():
                data = yf.download(
                    list(symbols),
                    period=HISTORY_PERIOD,
                    progress=False,
                    auto_adjust=True,
                    group_by="column",
                )
            if data is None or data.empty:
                return None
            return data
        except Exception:  # noqa: BLE001 - scoring is best-effort
            return None

    return _PRICE_CACHE.get(symbols, fetch)


def _series(data: pd.DataFrame, field: str, symbol: str) -> pd.Series | None:
    try:
        col = data[field]
    except Exception:  # noqa: BLE001
        return None
    if isinstance(col, pd.DataFrame):
        if symbol in col.columns:
            return col[symbol].dropna()
        return None
    # Single-ticker download: field is already the Series for that symbol.
    return col.dropna()


def _beta(sym_ret: pd.Series, idx_ret: pd.Series) -> float:
    joined = pd.concat([sym_ret, idx_ret], axis=1).dropna()
    if len(joined) < 20:
        return 1.0
    idx_var = float(joined.iloc[:, 1].var())
    if not idx_var or math.isnan(idx_var):
        return 1.0
    cov = float(joined.cov().iloc[0, 1])
    beta = cov / idx_var
    if math.isnan(beta):
        return 1.0
    return max(0.0, min(3.0, beta))


def _vol_multiplier(ratio: float | None) -> float:
    """Volume confirmation: <1x dampens, >1x boosts, clamped to [0.7, 1.25]."""
    if ratio is None or math.isnan(ratio):
        return 1.0
    return max(0.7, min(1.25, 0.6 + 0.4 * ratio))


def _event_position(index: pd.DatetimeIndex, published: datetime) -> int | None:
    """First trading bar on/after the publication date (the session that reacts)."""
    pub_date = published.astimezone(timezone.utc).date()
    for i, ts in enumerate(index):
        if ts.date() >= pub_date:
            return i
    return None


class _SymbolModel:
    """Per-symbol cached returns/volatility used to score that symbol's articles."""

    def __init__(self, close: pd.Series, volume: pd.Series | None, idx_ret: pd.Series):
        self.close = close
        self.ret = close.pct_change()
        self.sigma = self.ret.rolling(VOL_LOOKBACK).std()
        self.full_sigma = float(self.ret.std()) if len(self.ret.dropna()) > 2 else None
        self.beta = _beta(self.ret, idx_ret)
        self.idx_ret = idx_ret
        if volume is not None and not volume.empty:
            self.volume = volume
            self.avg_volume = volume.rolling(VOL_LOOKBACK).mean()
        else:
            self.volume = None
            self.avg_volume = None

    def score(self, published: datetime) -> dict[str, Any] | None:
        pos = _event_position(self.close.index, published)
        if pos is None or pos < 1:
            return None
        try:
            r = float(self.close.iloc[pos] / self.close.iloc[pos - 1] - 1.0)
        except (IndexError, ZeroDivisionError, ValueError):
            return None
        if math.isnan(r):
            return None

        # Market-adjusted (abnormal) return on the event day.
        idx_r = 0.0
        try:
            event_date = self.close.index[pos]
            if event_date in self.idx_ret.index:
                idx_val = self.idx_ret.loc[event_date]
                if isinstance(idx_val, pd.Series):
                    idx_val = idx_val.iloc[0]
                if idx_val is not None and not math.isnan(float(idx_val)):
                    idx_r = float(idx_val)
        except Exception:  # noqa: BLE001
            idx_r = 0.0
        abnormal = r - self.beta * idx_r

        # Standardize by the stock's normal daily volatility (known pre-event).
        sigma = None
        if pos - 1 < len(self.sigma):
            s = self.sigma.iloc[pos - 1]
            sigma = float(s) if s is not None and not math.isnan(float(s)) else None
        if sigma is None or sigma == 0:
            sigma = self.full_sigma
        if not sigma or sigma == 0 or math.isnan(sigma):
            return None
        z = abnormal / sigma

        # Volume confirmation.
        vol_ratio = None
        if self.volume is not None and self.avg_volume is not None and pos < len(self.volume):
            avg = self.avg_volume.iloc[pos]
            try:
                if avg and not math.isnan(float(avg)) and float(avg) > 0:
                    vol_ratio = float(self.volume.iloc[pos]) / float(avg)
            except (ValueError, TypeError):
                vol_ratio = None

        magnitude = math.tanh(abs(z) / Z_REF)
        base = min(100.0, 100.0 * magnitude * _vol_multiplier(vol_ratio))
        direction = "up" if abnormal > 0 else "down" if abnormal < 0 else "flat"
        return {
            "relevanceBase": base,
            "relevanceScore": int(round(base)),
            "reactionPct": round(r * 100.0, 2),
            "abnormalPct": round(abnormal * 100.0, 2),
            "sigma": round(z, 2),
            "volumeRatio": round(vol_ratio, 2) if vol_ratio is not None else None,
            "direction": direction,
        }


def _recency_weight(published: datetime | None, now: datetime) -> float:
    if published is None:
        return 0.0
    age_days = max(0.0, (now - published).total_seconds() / 86400.0)
    return 0.5 ** (age_days / RECENCY_HALFLIFE_DAYS)


def score_and_rank(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Annotate each news item with a relevance score and return them ranked by
    relevance blended with recency. Items without usable price data keep a null
    score and sort after scored ones (by recency). Best-effort: on any failure the
    items are returned in recency order, unscored."""
    if not items:
        return []

    now = datetime.now(timezone.utc)
    for it in items:
        it["_published_dt"] = _parse_dt(it.get("published"))

    symbols = tuple(sorted({str(it["symbol"]).upper() for it in items if it.get("symbol")}))
    download_symbols = tuple(sorted(set(symbols) | {INDEX_SYMBOL}))
    data = _bulk_history(download_symbols)

    models: dict[str, _SymbolModel] = {}
    if data is not None:
        idx_close = _series(data, "Close", INDEX_SYMBOL)
        idx_ret = idx_close.pct_change() if idx_close is not None else pd.Series(dtype=float)
        for sym in symbols:
            close = _series(data, "Close", sym)
            if close is None or len(close) < VOL_LOOKBACK:
                continue
            volume = _series(data, "Volume", sym)
            try:
                models[sym] = _SymbolModel(close, volume, idx_ret)
            except Exception:  # noqa: BLE001
                continue

    scored: list[dict[str, Any]] = []
    unscored: list[dict[str, Any]] = []
    for it in items:
        sym = str(it.get("symbol") or "").upper()
        published = it.get("_published_dt")
        result = None
        model = models.get(sym)
        if model is not None and published is not None:
            result = model.score(published)

        if result is not None:
            it.update(result)
            recency = _recency_weight(published, now)
            it["_rank"] = result["relevanceBase"] * (0.25 + 0.75 * recency)
            it.pop("relevanceBase", None)
            scored.append(it)
        else:
            it["relevanceScore"] = None
            it["reactionPct"] = None
            it["sigma"] = None
            it["direction"] = None
            it["_rank"] = -1.0
            unscored.append(it)

    scored.sort(key=lambda a: a.get("_rank", 0.0), reverse=True)
    unscored.sort(key=lambda a: (a.get("published") or ""), reverse=True)
    ordered = scored + unscored
    for it in ordered:
        it.pop("_rank", None)
        it.pop("_published_dt", None)
    return ordered


def _neutral_sentiment(detail: str) -> dict[str, Any]:
    return {
        "sentiment": "neutral",
        "net": 0.0,
        "bull": 0,
        "bear": 0,
        "count": 0,
        "topRelevance": 0,
        "detail": detail,
    }


def aggregate_symbol_sentiment(
    scored_items: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Group already-scored news items by symbol and compute a relevance-weighted
    directional sentiment.

    Each input item is expected to carry the annotations added by
    :func:`score_and_rank` / :func:`score_symbol_intraday` — namely
    ``relevanceScore`` (int 0-100) and ``direction`` ("up"/"down"/"flat").

    Returns ``{SYMBOL: {"sentiment", "net", "bull", "bear", "count",
    "topRelevance", "detail"}}`` where ``net`` is in -1..+1 and ``detail`` is a
    concise plain-text sourcing string suitable for an HTML title attribute (the
    frontend escapes it).
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for it in scored_items or []:
        sym = str(it.get("symbol") or "").upper()
        if not sym:
            continue
        groups.setdefault(sym, []).append(it)

    result: dict[str, dict[str, Any]] = {}
    for sym, items in groups.items():
        weight_sum = 0.0
        signed_sum = 0.0
        bull = 0
        bear = 0
        count = 0
        top_relevance = 0
        max_relevance = 0
        for it in items:
            score = it.get("relevanceScore")
            direction = it.get("direction")
            if score is None or direction is None:
                continue
            try:
                w = max(float(score), 0.0)
            except (TypeError, ValueError):
                continue
            sign = 1 if direction == "up" else -1 if direction == "down" else 0
            weight_sum += w
            signed_sum += w * sign
            count += 1
            if direction == "up":
                bull += 1
            elif direction == "down":
                bear += 1
            rel = int(round(w))
            top_relevance = max(top_relevance, rel)
            max_relevance = max(max_relevance, rel)

        # Materiality gate: require at least one genuinely market-moving article.
        if (
            count == 0
            or weight_sum <= 0
            or max_relevance < NEWS_SENTIMENT_MIN_RELEVANCE
        ):
            result[sym] = _neutral_sentiment(
                "No materially-relevant news — defaulting to neutral"
            )
            continue

        net = signed_sum / weight_sum
        if net >= NEWS_SENTIMENT_BAND:
            label = "bullish"
        elif net <= -NEWS_SENTIMENT_BAND:
            label = "bearish"
        else:
            label = "neutral"

        article_word = "article" if count == 1 else "articles"
        detail = (
            f"News: {bull}\u2191 / {bear}\u2193 across {count} recent {article_word} "
            f"\u00b7 net {net:+.2f} \u00b7 top relevance {top_relevance}"
        )
        result[sym] = {
            "sentiment": label,
            "net": round(net, 4),
            "bull": bull,
            "bear": bear,
            "count": count,
            "topRelevance": top_relevance,
            "detail": detail,
        }

    return result


# --- Phase 2: intraday (30-minute) reaction scoring --------------------------

_NULL_FIELDS = (
    "relevanceScore",
    "reactionPct",
    "abnormalPct",
    "sigma",
    "volumeRatio",
    "direction",
    "reactionWindow",
)


def _null_score(item: dict[str, Any]) -> dict[str, Any]:
    for field in _NULL_FIELDS:
        item[field] = None
    return item


def _intraday_history(symbol: str) -> pd.DataFrame | None:
    """One throttled, cached fetch of recent 1-minute OHLCV for a symbol.

    Returns a frame indexed by tz-aware UTC timestamps, or None on any failure.
    """
    sym = symbol.upper()

    def fetch() -> pd.DataFrame | None:
        try:
            df = make_ticker(sym).history(
                period=INTRADAY_PERIOD,
                interval=INTRADAY_INTERVAL,
                prepost=True,
            )
            if df is None or df.empty:
                return None
            idx = df.index
            try:
                if getattr(idx, "tz", None) is None:
                    df.index = idx.tz_localize("UTC")
                else:
                    df.index = idx.tz_convert("UTC")
            except Exception:  # noqa: BLE001 - leave index as-is if conversion fails
                return None
            return df
        except Exception:  # noqa: BLE001 - scoring is best-effort
            return None

    return _INTRADAY_CACHE.get(sym, fetch)


class _IntradayModel:
    """Per-symbol 1-minute model used to score each article's 30-min reaction."""

    def __init__(
        self,
        close: pd.Series,
        volume: pd.Series | None,
        idx_close: pd.Series | None,
    ):
        self.close = close
        self.volume = volume if (volume is not None and not volume.empty) else None
        self.idx_close = idx_close if (idx_close is not None and not idx_close.empty) else None

        win = REACTION_WINDOW_MINUTES
        ret = close.pct_change()
        idx_ret = self.idx_close.pct_change() if self.idx_close is not None else pd.Series(dtype=float)
        self.beta = _beta(ret, idx_ret)

        # Intraday volatility = std of overlapping forward W-minute returns. This
        # is the stock's "normal" move over a reaction window, so a 3% jump on a
        # placid name still outranks 3% on a jittery one.
        fwd = (close.shift(-win) / close - 1.0).dropna()
        self.sigma = float(fwd.std()) if len(fwd) > 2 else None

        # Average W-minute window volume across the sample (for the volume ratio).
        self.avg_window_vol: float | None = None
        if self.volume is not None:
            roll = self.volume.rolling(win).sum()
            try:
                avg = float(roll.mean())
            except (TypeError, ValueError):
                avg = float("nan")
            if avg and not math.isnan(avg) and avg > 0:
                self.avg_window_vol = avg

        self.start = close.index[0] if len(close) else None
        self.end = close.index[-1] if len(close) else None

    def _window_return(self, series: pd.Series, pub, end_ts) -> float | None:
        i0 = series.index.searchsorted(pub, side="left")
        i1 = series.index.searchsorted(end_ts, side="left")
        if i0 >= len(series) or i1 >= len(series) or i1 <= i0:
            return None
        try:
            p0 = float(series.iloc[i0])
            p1 = float(series.iloc[i1])
        except (IndexError, ValueError, TypeError):
            return None
        if p0 <= 0 or math.isnan(p0) or math.isnan(p1):
            return None
        return p1 / p0 - 1.0

    def score(self, published: datetime) -> dict[str, Any] | None:
        if self.start is None or self.end is None or self.sigma in (None, 0):
            return None
        try:
            pub = pd.Timestamp(published)
            pub = pub.tz_localize("UTC") if pub.tzinfo is None else pub.tz_convert("UTC")
        except Exception:  # noqa: BLE001
            return None

        win = pd.Timedelta(minutes=REACTION_WINDOW_MINUTES)
        end_ts = pub + win
        # The article must sit inside the intraday coverage with a full window after it.
        if pub < self.start or end_ts > self.end:
            return None

        raw = self._window_return(self.close, pub, end_ts)
        if raw is None:
            return None

        idx_r = 0.0
        if self.idx_close is not None:
            idx_window = self._window_return(self.idx_close, pub, end_ts)
            if idx_window is not None:
                idx_r = idx_window
        abnormal = raw - self.beta * idx_r

        sigma = self.sigma
        if not sigma or sigma == 0 or math.isnan(sigma):
            return None
        z = abnormal / sigma

        vol_ratio = None
        if self.volume is not None and self.avg_window_vol:
            i0 = self.volume.index.searchsorted(pub, side="left")
            i1 = self.volume.index.searchsorted(end_ts, side="left")
            if i0 < len(self.volume) and i1 <= len(self.volume) and i1 > i0:
                try:
                    win_vol = float(self.volume.iloc[i0:i1].sum())
                    if not math.isnan(win_vol):
                        vol_ratio = win_vol / self.avg_window_vol
                except (ValueError, TypeError):
                    vol_ratio = None

        magnitude = math.tanh(abs(z) / Z_REF)
        base = min(100.0, 100.0 * magnitude * _vol_multiplier(vol_ratio))
        direction = "up" if abnormal > 0 else "down" if abnormal < 0 else "flat"
        return {
            "relevanceScore": int(round(base)),
            "reactionPct": round(raw * 100.0, 2),
            "abnormalPct": round(abnormal * 100.0, 2),
            "sigma": round(z, 2),
            "volumeRatio": round(vol_ratio, 2) if vol_ratio is not None else None,
            "direction": direction,
            "reactionWindow": f"{REACTION_WINDOW_MINUTES}m",
        }


def _build_intraday_model(symbol: str) -> _IntradayModel | None:
    df = _intraday_history(symbol)
    if df is None or df.empty or "Close" not in df:
        return None
    close = df["Close"].dropna()
    if len(close) <= REACTION_WINDOW_MINUTES + 2:
        return None
    volume = df["Volume"].dropna() if "Volume" in df else None
    idx_df = _intraday_history(INDEX_SYMBOL)
    idx_close = None
    if idx_df is not None and not idx_df.empty and "Close" in idx_df:
        idx_close = idx_df["Close"].dropna()
    try:
        return _IntradayModel(close, volume, idx_close)
    except Exception:  # noqa: BLE001
        return None


def _build_daily_model(symbol: str) -> _SymbolModel | None:
    """A single-symbol Phase 1 daily model, used as the intraday fallback tier."""
    sym = symbol.upper()
    data = _bulk_history(tuple(sorted({sym, INDEX_SYMBOL})))
    if data is None:
        return None
    idx_close = _series(data, "Close", INDEX_SYMBOL)
    idx_ret = idx_close.pct_change() if idx_close is not None else pd.Series(dtype=float)
    close = _series(data, "Close", sym)
    if close is None or len(close) < VOL_LOOKBACK:
        return None
    volume = _series(data, "Volume", sym)
    try:
        return _SymbolModel(close, volume, idx_ret)
    except Exception:  # noqa: BLE001
        return None


def score_symbol_intraday(
    symbol: str, items: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Annotate one symbol's news with an intraday (30-min) reaction score.

    For each article we measure the stock's return in the REACTION_WINDOW_MINUTES
    after publication, strip out SPY's move (beta-adjusted), standardize by the
    stock's normal intraday volatility, and confirm with volume — the same shape
    as Phase 1 but at minute resolution, tagged ``reactionWindow="30m"``.

    Articles too old for 1m data (or with missing bars around them) fall back to
    the Phase 1 daily score tagged ``reactionWindow="1d"``; if even daily fails,
    the article keeps null scores. Best-effort: any failure → null scores, never
    raises. The list order is preserved; the frontend handles sorting.
    """
    if not items:
        return []
    try:
        return _score_symbol_intraday_impl(symbol, items)
    except Exception:  # noqa: BLE001 - never 500 the endpoint
        return [_null_score(it) for it in items]


def _score_symbol_intraday_impl(
    symbol: str, items: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    sym = (symbol or "").upper()
    now = datetime.now(timezone.utc)

    intraday_model = _build_intraday_model(sym)

    # The daily fallback hits the network, so only build it if an article needs it.
    daily_cache: dict[str, _SymbolModel | None] = {}

    def daily_model() -> _SymbolModel | None:
        if "model" not in daily_cache:
            try:
                daily_cache["model"] = _build_daily_model(sym)
            except Exception:  # noqa: BLE001
                daily_cache["model"] = None
        return daily_cache["model"]

    annotated: list[dict[str, Any]] = []
    for it in items:
        published = _parse_dt(it.get("published"))
        result: dict[str, Any] | None = None

        if published is not None:
            age_days = (now - published).total_seconds() / 86400.0
            if intraday_model is not None and 0 <= age_days <= INTRADAY_MAX_AGE_DAYS:
                result = intraday_model.score(published)

            if result is None:
                model = daily_model()
                if model is not None:
                    daily_res = model.score(published)
                    if daily_res is not None:
                        daily_res.pop("relevanceBase", None)
                        daily_res["reactionWindow"] = "1d"
                        result = daily_res

        if result is not None:
            _null_score(it)  # ensure every field exists, then fill the computed ones
            it.update(result)
        else:
            _null_score(it)
        annotated.append(it)

    return annotated
