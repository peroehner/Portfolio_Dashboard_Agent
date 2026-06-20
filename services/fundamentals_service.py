"""Fundamentals + recent news enrichment for assessment context.

Provides a compact, model-friendly snapshot of company fundamentals and recent
headlines so the LLM assessment has more to reason about than price alone.

Fundamentals come from yfinance (already a dependency, no API key required).
News is pluggable via NEWS_PROVIDER:
  - "finnhub": true per-ticker company news (needs FINNHUB_API_KEY)
  - "yfinance": yfinance Ticker.news (default fallback, no key)
When NEWS_PROVIDER is unset, Finnhub is used automatically if a key is present,
otherwise yfinance. Finnhub failures fall back to yfinance.
"""
from __future__ import annotations

import json
import logging
import os
import random
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any

import certifi
import yfinance as yf

from services.market_cache import CACHE_MISS, TtlCache, make_ticker, ticker_info_cache

# Finnhub's free tier allows ~60 API calls/minute. A whole-portfolio fetch can
# burst past that, causing 429s. An optional global minimum interval between
# Finnhub requests smooths the burst. It's OFF by default because a blocking
# throttle on the synchronous bulk endpoint could exceed the server request
# timeout for large portfolios; we instead rely on retry-on-429 plus not caching
# empty results (so reloads converge). Set FINNHUB_MIN_INTERVAL_SECONDS to enable.
_finnhub_min_interval = float(os.environ.get("FINNHUB_MIN_INTERVAL_SECONDS", "0"))
_finnhub_throttle_lock = threading.Lock()
_finnhub_last_call = [0.0]


def _finnhub_throttle() -> None:
    if _finnhub_min_interval <= 0:
        return
    with _finnhub_throttle_lock:
        wait = _finnhub_min_interval - (time.monotonic() - _finnhub_last_call[0])
        if wait > 0:
            time.sleep(wait)
        _finnhub_last_call[0] = time.monotonic()


# Yahoo's analyst price-target endpoint is reliable in isolation but drops calls
# when several fire at once during the concurrent bulk fetch. Spacing them out
# (ON by default) makes them succeed without poisoning the cache.
_targets_min_interval = float(os.environ.get("ANALYST_TARGETS_MIN_INTERVAL_SECONDS", "0.4"))
_targets_throttle_lock = threading.Lock()
_targets_last_call = [0.0]


def _analyst_targets_throttle() -> None:
    if _targets_min_interval <= 0:
        return
    with _targets_throttle_lock:
        wait = _targets_min_interval - (time.monotonic() - _targets_last_call[0])
        if wait > 0:
            time.sleep(wait)
        _targets_last_call[0] = time.monotonic()

logger = logging.getLogger(__name__)

_news_ttl = float(os.environ.get("NEWS_CACHE_TTL_SECONDS", "3600"))
_news_max = int(os.environ.get("NEWS_CACHE_MAX_ENTRIES", "48"))
news_cache: TtlCache = TtlCache(_news_ttl, _news_max)

_fund_ttl = float(os.environ.get("FUNDAMENTALS_CACHE_TTL_SECONDS", "21600"))  # 6h
_fund_max = int(os.environ.get("FUNDAMENTALS_CACHE_MAX_ENTRIES", "128"))
finnhub_fundamentals_cache: TtlCache = TtlCache(_fund_ttl, _fund_max)

# Analyst price targets are cached on their own so a transient fetch failure is
# retried on the next request instead of being frozen inside the fundamentals
# blob for the full TTL (only successful, non-empty results are stored).
analyst_targets_cache: TtlCache = TtlCache(_fund_ttl, _fund_max)

# Finnhub /stock/metric "metric" keys -> (group, normalized key).
# These are plain ratios with the same convention as yfinance (no scaling).
_FINNHUB_RATIO_FIELDS = {
    "peTTM": ("valuation", "trailingPe"),
    "pbAnnual": ("valuation", "priceToBook"),
    "psTTM": ("valuation", "priceToSales"),
    "currentRatioAnnual": ("financialHealth", "currentRatio"),
    "quickRatioAnnual": ("financialHealth", "quickRatio"),
    "beta": ("profile", "beta"),
    "52WeekHigh": ("priceRange", "high52w"),
    "52WeekLow": ("priceRange", "low52w"),
}
# Finnhub reports these as percentages (e.g. 45.2); yfinance/the UI expect a
# fraction (0.452), so divide by 100.
_FINNHUB_PCT_AS_FRACTION = {
    "grossMarginTTM": ("growthProfitability", "grossMargin"),
    "operatingMarginTTM": ("growthProfitability", "operatingMargin"),
    "netProfitMarginTTM": ("growthProfitability", "profitMargin"),
    "roeTTM": ("growthProfitability", "returnOnEquity"),
    "revenueGrowthTTMYoy": ("growthProfitability", "revenueGrowth"),
    "epsGrowthTTMYoy": ("growthProfitability", "earningsGrowth"),
}

# Map yfinance `info` keys -> normalized fundamentals keys we expose to the model.
_VALUATION_FIELDS = {
    "trailingPE": "trailingPe",
    "forwardPE": "forwardPe",
    "priceToBook": "priceToBook",
    "priceToSalesTrailing12Months": "priceToSales",
    "pegRatio": "pegRatio",
    "enterpriseToEbitda": "evToEbitda",
}
_GROWTH_PROFIT_FIELDS = {
    "revenueGrowth": "revenueGrowth",
    "earningsGrowth": "earningsGrowth",
    "grossMargins": "grossMargin",
    "operatingMargins": "operatingMargin",
    "profitMargins": "profitMargin",
    "returnOnEquity": "returnOnEquity",
}
_HEALTH_FIELDS = {
    "debtToEquity": "debtToEquity",
    "currentRatio": "currentRatio",
    "quickRatio": "quickRatio",
    "freeCashflow": "freeCashflow",
    "totalCash": "totalCash",
    "totalDebt": "totalDebt",
}
_PROFILE_FIELDS = {
    "sector": "sector",
    "industry": "industry",
    "marketCap": "marketCap",
    "beta": "beta",
    "dividendYield": "dividendYield",
}
_ANALYST_FIELDS = {
    "recommendationKey": "recommendationKey",
    "numberOfAnalystOpinions": "analystCount",
    "targetMeanPrice": "targetMean",
    "targetHighPrice": "targetHigh",
    "targetLowPrice": "targetLow",
}
_RANGE_FIELDS = {
    "fiftyTwoWeekHigh": "high52w",
    "fiftyTwoWeekLow": "low52w",
    "fiftyDayAverage": "ma50",
    "twoHundredDayAverage": "ma200",
}


class FundamentalsService:
    def __init__(self) -> None:
        self.enabled = os.environ.get("ASSESSMENT_FUNDAMENTALS", "1").strip().lower() not in (
            "0",
            "false",
            "no",
        )
        self.provider = os.environ.get("FUNDAMENTALS_PROVIDER", "yfinance").strip().lower()
        self.news_limit = int(os.environ.get("ASSESSMENT_NEWS_LIMIT", "6"))
        self.news_provider = os.environ.get("NEWS_PROVIDER", "").strip().lower()
        self.finnhub_api_key = os.environ.get("FINNHUB_API_KEY", "").strip()
        self.finnhub_news_days = int(os.environ.get("FINNHUB_NEWS_DAYS", "30"))

    def active_news_provider(self) -> str:
        if self.news_provider in ("finnhub", "yfinance"):
            if self.news_provider == "finnhub" and not self.finnhub_api_key:
                return "yfinance"
            return self.news_provider
        return "finnhub" if self.finnhub_api_key else "yfinance"

    def get_enrichment(self, symbol: str) -> dict[str, Any]:
        """Return {fundamentals, recentNews} for a symbol; empty dicts on failure."""
        if not self.enabled:
            return {"fundamentals": {}, "recentNews": []}
        symbol = symbol.upper()
        return {
            "fundamentals": self.fetch_fundamentals(symbol),
            "recentNews": self.fetch_recent_news(symbol),
        }

    def get_enrichment_bulk(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        """Fetch enrichment for many symbols in parallel; keyed by upper-cased symbol."""
        unique = [s.upper() for s in dict.fromkeys(symbols)]
        if not unique:
            return {}
        if not self.enabled:
            return {s: {"fundamentals": {}, "recentNews": []} for s in unique}

        workers = max(1, min(int(os.environ.get("FUNDAMENTALS_BULK_WORKERS", "4")), len(unique)))
        results: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for symbol, enrichment in zip(unique, pool.map(self.get_enrichment, unique)):
                results[symbol] = enrichment
        return results

    def fetch_fundamentals(self, symbol: str) -> dict[str, Any]:
        """yfinance first; backfill from Finnhub when core financials are missing.

        On datacenter IPs (e.g. Render) and increasingly on residential IPs,
        Yahoo's quoteSummary often returns *partial* info: the price endpoint
        still yields marketCap while the valuation/profitability modules fail.
        A coarse "all empty" check would short-circuit the fallback and leave a
        mostly-blank row, so instead we trigger Finnhub whenever the core
        financials are missing and merge it into yfinance's gaps (yfinance wins
        where it has a value).
        """
        data = self._fetch_yfinance_fundamentals(symbol)
        if self._needs_finnhub(data) and self.finnhub_api_key:
            fh = self._cached_finnhub_fundamentals(symbol)
            if not self._is_empty_fundamentals(fh):
                data = self._merge_fundamentals(data, fh)
        # Backfill analyst price targets from their own cache. This runs outside
        # the fundamentals blob so a transient miss retries next time rather than
        # being frozen blank for the whole TTL.
        if isinstance(data, dict) and not self._has_analyst_targets(data):
            targets = self._cached_analyst_targets(symbol)
            if targets:
                analyst = dict(data.get("analyst") or {})
                for key, value in targets.items():
                    analyst.setdefault(key, value)
                data["analyst"] = analyst
        return data

    def _cached_finnhub_fundamentals(self, symbol: str) -> dict[str, Any]:
        """Finnhub fundamentals with caching of successful (non-empty) results only.

        Empty results (e.g. from a transient 429) are NOT cached, so a later
        retry can succeed instead of serving a stale blank for the whole TTL.
        """
        cached = finnhub_fundamentals_cache.peek(symbol)
        if cached is not CACHE_MISS:
            return cached
        try:
            fh = self._fetch_finnhub_fundamentals(symbol)
        except Exception as exc:  # noqa: BLE001 - network/3rd-party failures are non-fatal
            logger.warning("Finnhub fundamentals failed for %s: %s", symbol, exc)
            return {}
        if not self._is_empty_fundamentals(fh):
            finnhub_fundamentals_cache.put(symbol, fh)
        return fh

    def _fetch_yfinance_fundamentals(self, symbol: str) -> dict[str, Any]:
        if self.provider != "yfinance":
            logger.warning("Unknown FUNDAMENTALS_PROVIDER=%s, falling back to yfinance", self.provider)
        try:
            info = ticker_info_cache.get(symbol, lambda: make_ticker(symbol).info)
        except Exception as exc:  # noqa: BLE001 - network/3rd-party failures are non-fatal
            logger.warning("Failed to fetch fundamentals for %s: %s", symbol, exc)
            return {}
        if not isinstance(info, dict):
            return {}

        return {
            "valuation": self._collect(info, _VALUATION_FIELDS),
            "growthProfitability": self._collect(info, _GROWTH_PROFIT_FIELDS),
            "financialHealth": self._collect(info, _HEALTH_FIELDS),
            "profile": self._collect(info, _PROFILE_FIELDS),
            "analyst": self._collect(info, _ANALYST_FIELDS),
            "priceRange": self._collect(info, _RANGE_FIELDS),
        }

    def _fetch_finnhub_fundamentals(self, symbol: str) -> dict[str, Any]:
        if not self.finnhub_api_key:
            return {}
        token = urllib.parse.quote(self.finnhub_api_key)
        qsym = urllib.parse.quote(symbol)
        out: dict[str, dict[str, Any]] = {
            "valuation": {},
            "growthProfitability": {},
            "financialHealth": {},
            "profile": {},
            "analyst": {},
            "priceRange": {},
        }

        metric = self._finnhub_get(
            f"https://finnhub.io/api/v1/stock/metric?symbol={qsym}&metric=all&token={token}",
            symbol,
            "metric",
        )
        metric = metric.get("metric") if isinstance(metric, dict) else None
        if isinstance(metric, dict):
            for src, (grp, key) in _FINNHUB_RATIO_FIELDS.items():
                self._put_num(out[grp], key, metric.get(src))
            for src, (grp, key) in _FINNHUB_PCT_AS_FRACTION.items():
                value = metric.get(src)
                if isinstance(value, (int, float)):
                    out[grp][key] = round(float(value) / 100.0, 4)
            self._put_num(out["valuation"], "forwardPe", metric.get("forwardPE"))
            self._put_num(out["valuation"], "evToEbitda", metric.get("evEbitdaTTM"))
            # yfinance expresses debt/equity as a percentage-like number (e.g. 158),
            # Finnhub as a raw ratio (1.58) — scale to match the UI's expectation.
            de = self._first_num(
                metric,
                "totalDebt/totalEquityAnnual",
                "totalDebt/totalEquityQuarterly",
                "longTermDebt/equityAnnual",
            )
            if de is not None:
                out["financialHealth"]["debtToEquity"] = round(de * 100.0, 4)
            dy = self._first_num(metric, "dividendYieldIndicatedAnnual", "currentDividendYieldTTM")
            if dy is not None:
                out["profile"]["dividendYield"] = round(dy, 4)

        profile = self._finnhub_get(
            f"https://finnhub.io/api/v1/stock/profile2?symbol={qsym}&token={token}",
            symbol,
            "profile2",
        )
        if isinstance(profile, dict):
            industry = profile.get("finnhubIndustry")
            if industry:
                out["profile"]["sector"] = str(industry)
            mcap = profile.get("marketCapitalization")  # in millions of currency
            if isinstance(mcap, (int, float)) and mcap:
                out["profile"]["marketCap"] = round(float(mcap) * 1_000_000, 2)

        recs = self._finnhub_get(
            f"https://finnhub.io/api/v1/stock/recommendation?symbol={qsym}&token={token}",
            symbol,
            "recommendation",
        )
        rec = self._latest_recommendation(recs)
        if rec:
            out["analyst"].update(rec)

        # Finnhub's free metrics lack moving averages and absolute cash/debt/FCF.
        # Backfill those from yfinance's history + statement endpoints, which use
        # different Yahoo APIs than the often-blocked quoteSummary (.info) and so
        # may still respond on datacenter IPs. Only exact values are used — never
        # approximations — so columns stay blank rather than showing wrong data.
        for key, value in self._history_moving_averages(symbol).items():
            self._put_num(out["priceRange"], key, value)
        for key, value in self._statement_financials(symbol).items():
            self._put_num(out["financialHealth"], key, value)

        # Note: analyst price targets are intentionally NOT fetched here. They are
        # handled by _cached_analyst_targets() outside this cached blob so a
        # transient failure does not get baked into the 6h fundamentals cache.
        return {grp: vals for grp, vals in out.items() if vals}

    def _history_moving_averages(self, symbol: str) -> dict[str, Any]:
        try:
            closes = make_ticker(symbol).history(period="1y", auto_adjust=True)["Close"].dropna()
        except Exception as exc:  # noqa: BLE001 - network/3rd-party failures are non-fatal
            logger.warning("History MA fetch failed for %s: %s", symbol, exc)
            return {}
        out: dict[str, Any] = {}
        if len(closes) >= 50:
            out["ma50"] = float(closes.tail(50).mean())
        if len(closes) >= 200:
            out["ma200"] = float(closes.tail(200).mean())
        return out

    @staticmethod
    def _has_analyst_targets(data: dict[str, Any]) -> bool:
        analyst = data.get("analyst") or {}
        return any(analyst.get(k) is not None for k in ("targetLow", "targetMean", "targetHigh"))

    def _cached_analyst_targets(self, symbol: str) -> dict[str, Any]:
        """Analyst price targets with caching of successful (non-empty) results only.

        Symbols with no analyst coverage (e.g. thin OTC names) legitimately
        return nothing; those are not cached, but they are also cheap and simply
        stay blank on each pass — never showing fabricated numbers.
        """
        cached = analyst_targets_cache.peek(symbol)
        if cached is not CACHE_MISS:
            return cached
        targets = self._analyst_price_targets(symbol)
        if targets:
            analyst_targets_cache.put(symbol, targets)
        return targets

    def _analyst_price_targets(self, symbol: str) -> dict[str, Any]:
        # Yahoo rate-limits this endpoint under the concurrent bulk warm, so a
        # single transient failure would otherwise cache a blank target column
        # for the whole TTL. A couple of quick retries make it converge.
        targets: Any = None
        for attempt in range(3):
            try:
                _analyst_targets_throttle()
                targets = make_ticker(symbol).analyst_price_targets
                break
            except Exception as exc:  # noqa: BLE001 - network/3rd-party failures are non-fatal
                if attempt == 2:
                    logger.warning("Analyst price target fetch failed for %s: %s", symbol, exc)
                    return {}
                # Longer, jittered backoff so retries escape the bulk-fetch burst.
                time.sleep(1.5 * (attempt + 1) + random.uniform(0, 0.75))
        if not isinstance(targets, dict):
            return {}
        out: dict[str, Any] = {}
        for src, dest in (("low", "targetLow"), ("mean", "targetMean"), ("high", "targetHigh")):
            value = targets.get(src)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value:
                out[dest] = float(value)
        return out

    def _statement_financials(self, symbol: str) -> dict[str, Any]:
        try:
            ticker = make_ticker(symbol)
            balance = ticker.balance_sheet
            cashflow = ticker.cashflow
        except Exception as exc:  # noqa: BLE001 - network/3rd-party failures are non-fatal
            logger.warning("Statement fetch failed for %s: %s", symbol, exc)
            return {}
        out: dict[str, Any] = {}
        cash = self._statement_value(
            balance, ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"]
        )
        if cash is not None:
            out["totalCash"] = cash
        debt = self._statement_value(balance, ["Total Debt"])
        if debt is not None:
            out["totalDebt"] = debt
        fcf = self._statement_value(cashflow, ["Free Cash Flow"])
        if fcf is not None:
            out["freeCashflow"] = fcf
        return out

    @staticmethod
    def _statement_value(frame: Any, row_names: list[str]) -> float | None:
        if frame is None or getattr(frame, "empty", True):
            return None
        for name in row_names:
            try:
                if name in frame.index:
                    series = frame.loc[name].dropna()
                    if len(series):
                        return float(series.iloc[0])
            except Exception:  # noqa: BLE001 - defensive against odd frame shapes
                continue
        return None

    def _finnhub_get(self, url: str, symbol: str, label: str) -> Any:
        try:
            return self._get_json(url)
        except Exception as exc:  # noqa: BLE001 - network/3rd-party failures are non-fatal
            logger.warning("Finnhub %s failed for %s: %s", label, symbol, exc)
            return None

    @staticmethod
    def _is_empty_fundamentals(data: Any) -> bool:
        return not isinstance(data, dict) or all(not v for v in data.values())

    @staticmethod
    def _needs_finnhub(data: Any) -> bool:
        """True when the meaningful financials are missing.

        Yahoo frequently returns only profile fields (e.g. marketCap) while the
        valuation and profitability modules fail. Those partial rows still look
        "non-empty", so we explicitly check the core groups here.
        """
        if not isinstance(data, dict):
            return True
        valuation = data.get("valuation") or {}
        growth = data.get("growthProfitability") or {}
        return not valuation or not growth

    @staticmethod
    def _merge_fundamentals(primary: dict[str, Any], secondary: dict[str, Any]) -> dict[str, Any]:
        """Fill gaps in ``primary`` (yfinance) with ``secondary`` (Finnhub).

        Existing non-empty values in ``primary`` are preserved; only missing or
        empty fields are taken from ``secondary``.
        """
        if not isinstance(secondary, dict) or not secondary:
            return primary
        if not isinstance(primary, dict):
            return dict(secondary)
        merged: dict[str, Any] = {}
        for group in set(primary) | set(secondary):
            base = dict(primary.get(group) or {})
            extra = secondary.get(group) or {}
            if isinstance(extra, dict):
                for key, value in extra.items():
                    if key not in base or base[key] in (None, "", {}, []):
                        base[key] = value
            if base:
                merged[group] = base
        return merged

    @staticmethod
    def _put_num(target: dict[str, Any], key: str, value: Any) -> None:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            target[key] = round(float(value), 4)

    @staticmethod
    def _first_num(source: dict[str, Any], *keys: str) -> float | None:
        for key in keys:
            value = source.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
        return None

    @staticmethod
    def _latest_recommendation(recs: Any) -> dict[str, Any]:
        if not isinstance(recs, list) or not recs:
            return {}
        entries = [r for r in recs if isinstance(r, dict)]
        if not entries:
            return {}
        latest = max(entries, key=lambda r: str(r.get("period", "")))
        buckets = {
            "strong_buy": int(latest.get("strongBuy") or 0),
            "buy": int(latest.get("buy") or 0),
            "hold": int(latest.get("hold") or 0),
            "sell": int(latest.get("sell") or 0),
            "strong_sell": int(latest.get("strongSell") or 0),
        }
        total = sum(buckets.values())
        if total <= 0:
            return {}
        return {"recommendationKey": max(buckets, key=lambda k: buckets[k]), "analystCount": total}

    def fetch_recent_news(self, symbol: str) -> list[dict[str, Any]]:
        if self.news_limit <= 0:
            return []
        provider = self.active_news_provider()
        try:
            if provider == "finnhub":
                return news_cache.get(f"finnhub:{symbol}", lambda: self._fetch_finnhub_news(symbol))
            return news_cache.get(f"yfinance:{symbol}", lambda: self._fetch_yfinance_news(symbol))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to fetch news for %s via %s: %s", symbol, provider, exc)
            if provider == "finnhub":
                try:
                    return news_cache.get(f"yfinance:{symbol}", lambda: self._fetch_yfinance_news(symbol))
                except Exception as fallback_exc:  # noqa: BLE001
                    logger.warning("yfinance news fallback failed for %s: %s", symbol, fallback_exc)
            return []

    def _fetch_yfinance_news(self, symbol: str) -> list[dict[str, Any]]:
        raw = make_ticker(symbol).news or []
        return self._normalize_news(raw)

    def _fetch_finnhub_news(self, symbol: str) -> list[dict[str, Any]]:
        if not self.finnhub_api_key:
            return self._fetch_yfinance_news(symbol)
        to_date = datetime.now(timezone.utc).date()
        from_date = to_date - timedelta(days=max(1, self.finnhub_news_days))
        url = (
            "https://finnhub.io/api/v1/company-news"
            f"?symbol={urllib.parse.quote(symbol)}"
            f"&from={from_date.isoformat()}&to={to_date.isoformat()}"
            f"&token={urllib.parse.quote(self.finnhub_api_key)}"
        )
        raw = self._get_json(url)
        return self._normalize_finnhub_news(raw)

    def _normalize_finnhub_news(self, raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list):
            return []
        ordered = sorted(
            (e for e in raw if isinstance(e, dict)),
            key=lambda e: e.get("datetime", 0) or 0,
            reverse=True,
        )
        items: list[dict[str, Any]] = []
        for entry in ordered:
            title = entry.get("headline")
            if not title:
                continue
            summary = entry.get("summary")
            url = entry.get("url")
            source = entry.get("source")
            items.append(
                {
                    "title": str(title).strip(),
                    "publisher": str(source).strip() if source else None,
                    "published": self._epoch_to_iso(entry.get("datetime")),
                    "link": str(url).strip() if url else None,
                    "summary": summary.strip()[:600] if isinstance(summary, str) and summary.strip() else None,
                }
            )
            if len(items) >= self.news_limit:
                break
        return items

    @staticmethod
    def _get_json(url: str) -> Any:
        ctx = ssl.create_default_context(cafile=certifi.where())
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        is_finnhub = "finnhub.io" in url
        attempts = 3 if is_finnhub else 1
        for attempt in range(attempts):
            if is_finnhub:
                _finnhub_throttle()
            try:
                with urllib.request.urlopen(req, timeout=20, context=ctx) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                # 429 (rate limited) is retryable with backoff; re-raise otherwise.
                if exc.code == 429 and attempt < attempts - 1:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise

    def _normalize_news(self, raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list):
            return []
        items: list[dict[str, Any]] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            # yfinance has used both a flat shape and a nested {"content": {...}} shape.
            content = entry.get("content") if isinstance(entry.get("content"), dict) else entry
            title = content.get("title") or entry.get("title")
            if not title:
                continue
            publisher = (
                content.get("provider", {}).get("displayName")
                if isinstance(content.get("provider"), dict)
                else content.get("publisher") or entry.get("publisher")
            )
            published = (
                content.get("pubDate")
                or content.get("displayTime")
                or self._epoch_to_iso(entry.get("providerPublishTime"))
            )
            items.append(
                {
                    "title": str(title).strip(),
                    "publisher": str(publisher).strip() if publisher else None,
                    "published": published,
                    "link": self._extract_link(content, entry),
                    "summary": self._extract_summary(content),
                }
            )
            if len(items) >= self.news_limit:
                break
        return items

    @staticmethod
    def _extract_link(content: dict[str, Any], entry: dict[str, Any]) -> str | None:
        for key in ("canonicalUrl", "clickThroughUrl"):
            candidate = content.get(key)
            if isinstance(candidate, dict) and candidate.get("url"):
                return str(candidate["url"]).strip()
        for source in (content, entry):
            for key in ("link", "url"):
                value = source.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return None

    @staticmethod
    def _extract_summary(content: dict[str, Any]) -> str | None:
        for key in ("summary", "description"):
            value = content.get(key)
            if isinstance(value, str) and value.strip():
                text = value.strip()
                return text[:600]
        return None

    @staticmethod
    def _epoch_to_iso(value: Any) -> str | None:
        try:
            if value is None:
                return None
            return time.strftime("%Y-%m-%d", time.gmtime(float(value)))
        except (TypeError, ValueError, OSError):
            return None

    @staticmethod
    def _collect(info: dict[str, Any], mapping: dict[str, str]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for source_key, target_key in mapping.items():
            value = info.get(source_key)
            if value is None:
                continue
            if isinstance(value, (int, float)):
                out[target_key] = round(float(value), 4)
            else:
                out[target_key] = value
        return out
