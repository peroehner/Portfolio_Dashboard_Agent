"""Buy-and-hold mark-to-market of today's holdings (past Progress).

Revalues current share counts at historical closes — ignores past adds/sells.
"""

from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from typing import Any, Callable

import pandas as pd

from services.market_cache import TtlCache, yf_throttle

logger = logging.getLogger(__name__)

SPY_SYMBOL = "SPY"
WINDOWS_DAYS = {"1M": 30, "3M": 91}
ATH_MIN_LOOKBACK_DAYS = 365
ATH_MAX_LOOKBACK_DAYS = 365 * 5

_PAST_PROGRESS_CACHE = TtlCache(
    float(os.environ.get("PAST_PROGRESS_CACHE_TTL_SECONDS", "3600")),
    max_entries=16,
)


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:  # NaN
        return None
    return out


def _parse_purchase_date(value: Any) -> date | None:
    if value is None:
        return None
    text = str(value).strip()[:10]
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def held_positions(holdings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Open positions with quantity > 0."""
    out: list[dict[str, Any]] = []
    for holding in holdings:
        qty = _safe_float(holding.get("quantity"))
        if qty is None or qty <= 0:
            continue
        symbol = str(holding.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        out.append({**holding, "symbol": symbol, "quantity": qty})
    return out


def ath_lookback_start(positions: list[dict[str, Any]], today: date | None = None) -> date:
    """max(1y, oldest purchase date), capped at ~5y."""
    today = today or date.today()
    floor = today - timedelta(days=ATH_MAX_LOOKBACK_DAYS)
    start = today - timedelta(days=ATH_MIN_LOOKBACK_DAYS)
    purchase_dates = [
        d for d in (_parse_purchase_date(p.get("purchaseDate")) for p in positions) if d is not None
    ]
    if purchase_dates:
        oldest = min(purchase_dates)
        if oldest < start:
            start = oldest
    if start < floor:
        start = floor
    return start


def _close_on_or_before(series: pd.Series, target: date) -> tuple[date, float] | None:
    if series is None or series.empty:
        return None
    # Normalize index to dates
    idx = pd.to_datetime(series.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_convert(None)
    dates = idx.date
    frame = pd.Series(series.to_numpy(dtype=float), index=dates)
    frame = frame[~pd.isna(frame)]
    if frame.empty:
        return None
    eligible = frame[frame.index <= target]
    if eligible.empty:
        return None
    d = eligible.index[-1]
    return d, float(eligible.iloc[-1])


def basket_value_at(
    positions: list[dict[str, Any]],
    closes: dict[str, pd.Series],
    target: date,
) -> tuple[float | None, int, int]:
    """Return (value, covered_count, total_positions) at target date."""
    total = len(positions)
    if total == 0:
        return None, 0, 0
    value = 0.0
    covered = 0
    for pos in positions:
        series = closes.get(pos["symbol"])
        hit = _close_on_or_before(series, target) if series is not None else None
        if hit is None:
            continue
        _d, price = hit
        if price <= 0:
            continue
        value += pos["quantity"] * price
        covered += 1
    if covered == 0:
        return None, 0, total
    return round(value, 2), covered, total


def basket_series(
    positions: list[dict[str, Any]],
    closes: dict[str, pd.Series],
    start: date,
    end: date,
) -> list[tuple[date, float]]:
    """Daily basket MTM for dates where at least one holding has a close.

    Only dates where *all* currently held names that have *any* history in range
    are present would be ideal; for ATH we use dates where coverage equals the
    max coverage seen (exclude sparse early days that understate the peak).
    """
    if not positions:
        return []

    # Collect trading dates from all series
    date_sets: list[set[date]] = []
    usable_symbols: list[str] = []
    for pos in positions:
        series = closes.get(pos["symbol"])
        if series is None or series.empty:
            continue
        idx = pd.to_datetime(series.index)
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_convert(None)
        dates = {d for d in idx.date if start <= d <= end}
        if not dates:
            continue
        date_sets.append(dates)
        usable_symbols.append(pos["symbol"])

    if not usable_symbols:
        return []

    # Prefer intersection so ATH isn't inflated by missing names; if empty, fall
    # back to union with partial coverage (still better than nothing).
    common = set.intersection(*date_sets) if date_sets else set()
    use_dates = sorted(common) if common else sorted(set.union(*date_sets))

    qty_by_symbol = {p["symbol"]: p["quantity"] for p in positions if p["symbol"] in usable_symbols}
    points: list[tuple[date, float]] = []
    for d in use_dates:
        total = 0.0
        ok = 0
        for symbol, qty in qty_by_symbol.items():
            hit = _close_on_or_before(closes[symbol], d)
            if hit is None:
                continue
            _hd, price = hit
            if price <= 0:
                continue
            # Only count if the close is for this exact day when using intersection;
            # for union mode accept on-or-before within a few days.
            if common and hit[0] != d:
                continue
            total += qty * price
            ok += 1
        if common:
            if ok == len(qty_by_symbol):
                points.append((d, round(total, 2)))
        elif ok > 0:
            points.append((d, round(total, 2)))
    return points


def position_values_at(
    positions: list[dict[str, Any]],
    closes: dict[str, pd.Series],
    target: date,
) -> list[dict[str, Any]]:
    """Per-symbol basket values at target date (for allocation pie charts)."""
    rows: list[dict[str, Any]] = []
    for pos in positions:
        series = closes.get(pos["symbol"])
        hit = _close_on_or_before(series, target) if series is not None else None
        if hit is None:
            continue
        _d, price = hit
        if price <= 0:
            continue
        value = round(float(pos["quantity"]) * price, 2)
        if value <= 0:
            continue
        rows.append({"symbol": pos["symbol"], "marketValue": value})
    return rows


def compute_window(
    *,
    value_then: float | None,
    value_now: float | None,
    spy_then: float | None,
    spy_now: float | None,
    covered: int,
    total: int,
) -> dict[str, Any] | None:
    if value_then is None or value_now is None or value_then <= 0 or total <= 0:
        return None
    return_pct = round((value_now - value_then) / value_then * 100, 2)
    spy_return_pct = None
    relative_pct = None
    if spy_then is not None and spy_now is not None and spy_then > 0:
        spy_return_pct = round((spy_now - spy_then) / spy_then * 100, 2)
        relative_pct = round(return_pct - spy_return_pct, 2)
    return {
        "valueThen": value_then,
        "valueNow": value_now,
        "returnPct": return_pct,
        "spyReturnPct": spy_return_pct,
        "relativePct": relative_pct,
        "coverage": {
            "heldWithPrices": covered,
            "heldTotal": total,
            "pct": round(covered / total * 100, 1) if total else 0.0,
        },
    }


def compute_ath(
    points: list[tuple[date, float]],
    value_now: float | None,
) -> dict[str, Any] | None:
    if not points:
        return None
    peak_date, peak_value = max(points, key=lambda p: (p[1], p[0]))
    if peak_value <= 0:
        return None
    delta_value = None
    delta_pct = None
    if value_now is not None:
        delta_value = round(value_now - peak_value, 2)
        delta_pct = round(delta_value / peak_value * 100, 2)
    return {
        "date": peak_date.isoformat(),
        "value": peak_value,
        "deltaValue": delta_value,
        "deltaPct": delta_pct,
    }


def compute_past_progress_from_closes(
    holdings: list[dict[str, Any]],
    closes: dict[str, pd.Series],
    *,
    as_of: date | None = None,
    value_now_override: float | None = None,
) -> dict[str, Any]:
    """Pure compute path — used by tests with mocked series."""
    as_of = as_of or date.today()
    positions = held_positions(holdings)
    total = len(positions)
    value_now = value_now_override
    if value_now is None:
        value_now, _, _ = basket_value_at(positions, closes, as_of)

    windows: dict[str, Any] = {}
    spy = closes.get(SPY_SYMBOL)
    for key, days in WINDOWS_DAYS.items():
        target = as_of - timedelta(days=days)
        value_then, covered, _tot = basket_value_at(positions, closes, target)
        spy_then = None
        spy_now = None
        if spy is not None:
            hit_then = _close_on_or_before(spy, target)
            hit_now = _close_on_or_before(spy, as_of)
            if hit_then:
                spy_then = hit_then[1]
            if hit_now:
                spy_now = hit_now[1]
        window = compute_window(
            value_then=value_then,
            value_now=value_now,
            spy_then=spy_then,
            spy_now=spy_now,
            covered=covered,
            total=total,
        )
        if window is not None:
            window["holdings"] = position_values_at(positions, closes, target)
            windows[key] = window

    start = ath_lookback_start(positions, as_of)
    points = basket_series(positions, closes, start, as_of)
    ath = compute_ath(points, value_now)
    if ath is not None:
        peak_date = date.fromisoformat(str(ath["date"])[:10])
        ath["holdings"] = position_values_at(positions, closes, peak_date)

    return {
        "asOf": as_of.isoformat(),
        "definition": "current_holdings_buy_hold",
        "windows": windows,
        "ath": ath,
    }


def _download_closes(symbols: list[str], start: date) -> dict[str, pd.Series]:
    if not symbols:
        return {}
    import yfinance as yf
    from services.market_cache import get_yf_session

    out: dict[str, pd.Series] = {}
    try:
        with yf_throttle():
            data = yf.download(
                symbols,
                start=start.isoformat(),
                progress=False,
                auto_adjust=True,
                group_by="column",
                session=get_yf_session(),
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Past progress download failed: %s", exc)
        return out

    if data is None or getattr(data, "empty", True):
        return out

    try:
        if len(symbols) == 1:
            sym = symbols[0]
            close = data["Close"].dropna()
            if not close.empty:
                out[sym] = close
        else:
            close = data["Close"]
            for sym in symbols:
                try:
                    series = close[sym].dropna()
                    if not series.empty:
                        out[sym] = series
                except (KeyError, TypeError, ValueError):
                    continue
    except Exception as exc:  # noqa: BLE001
        logger.warning("Past progress parse failed: %s", exc)
    return out


def build_past_progress(
    holdings: list[dict[str, Any]],
    *,
    value_now: float | None = None,
    fetch_closes: Callable[[list[str], date], dict[str, pd.Series]] | None = None,
) -> dict[str, Any] | None:
    """Fetch history and compute pastProgress for overview."""
    positions = held_positions(holdings)
    if not positions:
        return None

    today = date.today()
    start = ath_lookback_start(positions, today)
    symbols = sorted({p["symbol"] for p in positions} | {SPY_SYMBOL})
    fingerprint = tuple(
        (p["symbol"], round(float(p["quantity"]), 6), str(p.get("purchaseDate") or "")[:10])
        for p in sorted(positions, key=lambda x: x["symbol"])
    )
    cache_key = ("v2-holdings", today.isoformat(), fingerprint, round(float(value_now or 0), 2))

    def factory() -> dict[str, Any]:
        fetcher = fetch_closes or _download_closes
        closes = fetcher(symbols, start - timedelta(days=7))
        return compute_past_progress_from_closes(
            holdings,
            closes,
            as_of=today,
            value_now_override=value_now,
        )

    return _PAST_PROGRESS_CACHE.get(cache_key, factory)
