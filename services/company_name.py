"""Resolve display company names when yfinance .info is unavailable (e.g. on Render)."""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

_finnhub_name_cache: dict[str, str | None] = {}


def company_name_from_info(info: dict | None) -> str | None:
    if not isinstance(info, dict):
        return None
    for key in ("longName", "shortName"):
        value = info.get(key)
        if value:
            text = str(value).strip()
            if text:
                return text
    return None


def company_name_from_finnhub(symbol: str) -> str | None:
    symbol = symbol.upper()
    if symbol in _finnhub_name_cache:
        return _finnhub_name_cache[symbol]

    api_key = os.environ.get("FINNHUB_API_KEY", "").strip()
    if not api_key:
        _finnhub_name_cache[symbol] = None
        return None

    try:
        qsym = urllib.parse.quote(symbol)
        token = urllib.parse.quote(api_key)
        url = f"https://finnhub.io/api/v1/stock/profile2?symbol={qsym}&token={token}"
        with urllib.request.urlopen(url, timeout=12) as resp:
            data = json.loads(resp.read().decode())
        name = data.get("name") if isinstance(data, dict) else None
        result = str(name).strip() if name else None
        _finnhub_name_cache[symbol] = result
        return result
    except Exception as exc:
        logger.warning("Finnhub company name failed for %s: %s", symbol, exc)
        _finnhub_name_cache[symbol] = None
        return None


def resolve_company_name(symbol: str, info: dict | None = None) -> str | None:
    """Prefer yfinance info, then Finnhub profile2 name."""
    name = company_name_from_info(info)
    if name:
        return name
    return company_name_from_finnhub(symbol)
