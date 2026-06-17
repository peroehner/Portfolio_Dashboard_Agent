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
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any

import certifi
import yfinance as yf

from services.market_cache import TtlCache, ticker_info_cache

logger = logging.getLogger(__name__)

_news_ttl = float(os.environ.get("NEWS_CACHE_TTL_SECONDS", "3600"))
_news_max = int(os.environ.get("NEWS_CACHE_MAX_ENTRIES", "48"))
news_cache: TtlCache = TtlCache(_news_ttl, _news_max)

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

        workers = max(1, min(int(os.environ.get("FUNDAMENTALS_BULK_WORKERS", "8")), len(unique)))
        results: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for symbol, enrichment in zip(unique, pool.map(self.get_enrichment, unique)):
                results[symbol] = enrichment
        return results

    def fetch_fundamentals(self, symbol: str) -> dict[str, Any]:
        if self.provider != "yfinance":
            logger.warning("Unknown FUNDAMENTALS_PROVIDER=%s, falling back to yfinance", self.provider)
        try:
            info = ticker_info_cache.get(symbol, lambda: yf.Ticker(symbol).info)
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
        raw = yf.Ticker(symbol).news or []
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
        with urllib.request.urlopen(req, timeout=20, context=ctx) as response:
            return json.loads(response.read().decode("utf-8"))

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
