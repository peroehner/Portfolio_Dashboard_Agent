"""Shared per-symbol base assessments (one LLM run per ticker per UTC day).

User-specific thresholds, notes, and holdings are applied later by
``AssessmentOverlayService`` — see ``assessment_overlay_service.py``.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from db.database import get_connection
from services.fib_service import FibService
from services.fundamentals_service import FundamentalsService
from services.llm_client import LLMClient
from services.market_data_service import MarketDataService
from services.technical_signals_service import TechnicalSignalsService

ASSESSMENT_TECHNICALS = os.environ.get("ASSESSMENT_TECHNICALS", "1").lower() not in (
    "0",
    "false",
    "no",
    "off",
)
DEDUP_BASE_ASSESSMENT = os.environ.get("DEDUP_BASE_ASSESSMENT", "1").lower() not in (
    "0",
    "false",
    "no",
    "off",
)


def utc_today_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class SymbolAssessmentService:
    def __init__(self):
        self.fib_service = FibService()
        self.fundamentals_service = FundamentalsService()
        self.technical_signals_service = TechnicalSignalsService()
        self.llm_client = LLMClient()
        self.market_data_service = MarketDataService()

    def get_todays_base(self, symbol: str) -> dict[str, Any] | None:
        symbol = symbol.upper()
        as_of = utc_today_iso()
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT symbol, as_of_date, action, confidence, rationale, factors,
                       trading_recommendation, provider, analysis_json, created_at
                FROM symbol_assessment
                WHERE symbol = %s AND as_of_date = %s
                """,
                (symbol, as_of),
            ).fetchone()
        return self._row_to_base(row) if row else None

    def get_or_compute_today(self, symbol: str, *, force: bool = False) -> dict[str, Any]:
        symbol = symbol.upper()
        if DEDUP_BASE_ASSESSMENT and not force:
            cached = self.get_todays_base(symbol)
            if cached:
                cached["fromCache"] = True
                return cached

        context = self.build_base_context(symbol)
        if context.get("currentPrice") is None:
            raise ValueError(f"No market price available for {symbol}.")

        result = self.llm_client.generate_base_assessment(context)
        stored = self._save_base(symbol, utc_today_iso(), result, context)
        stored["fromCache"] = False
        return stored

    def build_base_context(self, symbol: str) -> dict[str, Any]:
        symbol = symbol.upper()
        market = self.market_data_service.get_market(symbol) or {}
        price = market.get("current_price")
        analyst = market.get("analystTarget1y")
        enrichment = self.fundamentals_service.get_enrichment(symbol)
        fib = self.fib_service.get_levels(symbol)

        upside_pct = None
        fib_distance = None
        if price and analyst and price > 0:
            upside_pct = round((analyst - price) / price * 100, 2)
        if price is not None:
            closest = self.fib_service.closest_level(symbol, price)
            if closest:
                fib_distance = closest.get("distancePct")

        return {
            "symbol": symbol,
            "currentPrice": price,
            "analystTarget1y": analyst,
            "fibLevels": fib.get("levels", []) if fib else [],
            "screening": {
                "upsidePct": upside_pct,
                "fibDistancePct": fib_distance,
            },
            "fundamentals": enrichment.get("fundamentals", {}),
            "recentNews": enrichment.get("recentNews", []),
            "technical": self._build_technical(symbol) if ASSESSMENT_TECHNICALS else None,
        }

    def _build_technical(self, symbol: str) -> dict[str, Any] | None:
        from db.database import get_prefer_computed_trends
        from services.technical_service import TechnicalService

        signals = self.technical_signals_service.get_signals(symbol)
        block: dict[str, Any] = dict(signals) if signals else {}

        if get_prefer_computed_trends():
            return block or None

        technical_service = TechnicalService()
        snapshot = technical_service.get_snapshot(symbol)
        if snapshot and snapshot.get("trends"):
            block["trendWaves"] = technical_service.trend_waves_for_symbol(symbol, snapshot)
        imported_fib = (
            technical_service.fib_from_snapshot(symbol, snapshot) if snapshot else None
        )
        if imported_fib and imported_fib.get("levels"):
            block["swing"] = {
                "source": "imported",
                "swingHigh": imported_fib.get("swingHigh"),
                "swingLow": imported_fib.get("swingLow"),
                "period": imported_fib.get("period"),
                "anchorTrend": imported_fib.get("anchorTrend"),
                "levels": imported_fib.get("levels", []),
            }
        return block or None

    def _save_base(
        self,
        symbol: str,
        as_of_date: str,
        result: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        factors_json = json.dumps(result.get("factors", []))
        analysis_json = json.dumps(
            {
                "actionSource": result.get("actionSource"),
                "context": {
                    "screening": context.get("screening"),
                    "technicalSummary": self._technical_summary(context.get("technical")),
                },
            }
        )
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO symbol_assessment (
                    symbol, as_of_date, action, confidence, rationale, factors,
                    trading_recommendation, provider, analysis_json
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (symbol, as_of_date) DO UPDATE SET
                    action = EXCLUDED.action,
                    confidence = EXCLUDED.confidence,
                    rationale = EXCLUDED.rationale,
                    factors = EXCLUDED.factors,
                    trading_recommendation = EXCLUDED.trading_recommendation,
                    provider = EXCLUDED.provider,
                    analysis_json = EXCLUDED.analysis_json,
                    created_at = app_now_text()
                """,
                (
                    symbol,
                    as_of_date,
                    result["action"],
                    result["confidence"],
                    result["rationale"],
                    factors_json,
                    None,
                    result["provider"],
                    analysis_json,
                ),
            )
            conn.commit()
            row = conn.execute(
                """
                SELECT symbol, as_of_date, action, confidence, rationale, factors,
                       trading_recommendation, provider, analysis_json, created_at
                FROM symbol_assessment
                WHERE symbol = %s AND as_of_date = %s
                """,
                (symbol, as_of_date),
            ).fetchone()
        base = self._row_to_base(row)
        assert base is not None
        if result.get("llmFallback"):
            base["llmFallback"] = True
            base["llmError"] = result.get("llmError")
        return base

    def _row_to_base(self, row) -> dict[str, Any] | None:
        if not row:
            return None
        factors = self._parse_json_field(row["factors"], default=[])
        analysis = self._parse_json_field(row.get("analysis_json"), default={})
        return {
            "symbol": row["symbol"],
            "asOfDate": row["as_of_date"],
            "action": row["action"],
            "confidence": row["confidence"],
            "rationale": row["rationale"],
            "factors": factors,
            "provider": row["provider"],
            "createdAt": row["created_at"],
            "analysisJson": analysis,
            "actionSource": (analysis or {}).get("actionSource"),
        }

    @staticmethod
    def _parse_json_field(raw, default):
        if not raw:
            return default
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return default

    @staticmethod
    def _technical_summary(technical: dict[str, Any] | None) -> dict[str, Any] | None:
        if not technical:
            return None
        confluence = technical.get("confluence") or {}
        patterns = technical.get("patterns") or []
        return {
            "confluenceBias": confluence.get("bias"),
            "patternCount": len(patterns),
        }
