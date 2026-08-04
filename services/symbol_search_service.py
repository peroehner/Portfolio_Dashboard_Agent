"""Ticker autocomplete search (Finnhub), used by Add Ticker on Holdings."""

from __future__ import annotations

import json
import logging
import os
import ssl
import urllib.parse
import urllib.request
from typing import Any

import certifi

logger = logging.getLogger(__name__)

_DEFAULT_LIMIT = 12
_MAX_LIMIT = 25


def search_tickers(query: str, *, limit: int = _DEFAULT_LIMIT) -> dict[str, Any]:
    """Return Finnhub search hits for Add Ticker autocomplete.

    When ``FINNHUB_API_KEY`` is missing, returns an empty result list with
    ``providerUnavailable`` so the UI can fall back to exact-symbol entry.
    """
    q = (query or "").strip()
    lim = max(1, min(int(limit or _DEFAULT_LIMIT), _MAX_LIMIT))
    if len(q) < 1:
        return {"query": q, "results": [], "providerUnavailable": False}

    api_key = os.environ.get("FINNHUB_API_KEY", "").strip()
    if not api_key:
        return {"query": q, "results": [], "providerUnavailable": True}

    try:
        qq = urllib.parse.quote(q)
        token = urllib.parse.quote(api_key)
        url = f"https://finnhub.io/api/v1/search?q={qq}&token={token}"
        ctx = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(url, timeout=12, context=ctx) as resp:
            data = json.loads(resp.read().decode())
    except Exception as exc:  # noqa: BLE001 - search is best-effort for the UI
        logger.warning("Finnhub ticker search failed for %r: %s", q, exc)
        return {"query": q, "results": [], "providerUnavailable": False, "error": str(exc)[:200]}

    raw = data.get("result") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        raw = []

    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in raw:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        results.append(
            {
                "symbol": symbol,
                "displaySymbol": str(row.get("displaySymbol") or symbol).strip() or symbol,
                "description": str(row.get("description") or "").strip(),
                "type": str(row.get("type") or "").strip(),
            }
        )
        if len(results) >= lim:
            break

    return {"query": q, "results": results, "providerUnavailable": False}
