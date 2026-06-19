import json
from typing import Any

from db.database import get_connection
from services.alerts_service import AlertsService
from services.fib_service import FibService
from services.fundamentals_service import FundamentalsService
from services.holdings_service import HoldingsService
from services.llm_client import LLMClient
from services.portfolio_service import PortfolioService
from services.screening_service import ScreeningService


class AssessmentService:
    MAX_ASSESSMENTS_PER_SYMBOL = 3

    def __init__(self):
        self.portfolio_service = PortfolioService()
        self.holdings_service = HoldingsService()
        self.alerts_service = AlertsService()
        self.fib_service = FibService()
        self.screening_service = ScreeningService()
        self.fundamentals_service = FundamentalsService()
        self.llm_client = LLMClient()

    def assess_symbol(self, symbol: str) -> dict[str, Any]:
        symbol = symbol.upper()
        symbol_data = self.portfolio_service.get_symbol(symbol)
        if symbol_data is None:
            raise ValueError(f"Symbol {symbol} not found.")

        context = self._build_context(symbol_data)
        result = self.llm_client.generate_assessment(context)
        return self._save_assessment(symbol, result, context)

    def assess_portfolio(self, symbols: list[str] | None = None) -> list[dict[str, Any]]:
        if symbols:
            return [self.assess_symbol(symbol) for symbol in symbols]

        assessments = []
        for item in self.portfolio_service.list_symbols():
            assessments.append(self.assess_symbol(item["symbol"]))
        return assessments

    def list_assessments(self, symbol: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        query = """
            SELECT id, symbol, action, confidence, rationale, factors,
                   note_synthesis, trading_recommendation, provider, created_at
            FROM assessments
        """
        params: list[Any] = []
        if symbol:
            query += " WHERE symbol = ?"
            params.append(symbol.upper())
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_assessment(row) for row in rows]

    def delete_assessment(self, assessment_id: int, symbol: str | None = None) -> bool:
        query = "DELETE FROM assessments WHERE id = ?"
        params: list[Any] = [assessment_id]
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol.upper())

        with get_connection() as conn:
            cursor = conn.execute(query, params)
            conn.commit()
            return cursor.rowcount > 0

    def _build_context(self, symbol_data: dict[str, Any]) -> dict[str, Any]:
        symbol = symbol_data["symbol"]
        fib = self.fib_service.get_levels(symbol)
        holding = self._holding_with_weight(symbol)
        screening = self.screening_service._score_symbol(symbol_data)
        notes = symbol_data.get("notes", [])

        note_syntheses = [note["synthesis"] for note in notes if note.get("synthesis")]
        unsynthesized = sum(1 for note in notes if not note.get("synthesis"))
        enrichment = self.fundamentals_service.get_enrichment(symbol)

        return {
            "symbol": symbol,
            "currentPrice": symbol_data.get("currentPrice"),
            "targetPrice": symbol_data.get("targetPrice"),
            "analystTarget1y": symbol_data.get("analystTarget1y"),
            "buyBelow": symbol_data.get("buyBelow"),
            "sellAbove": symbol_data.get("sellAbove"),
            "noteSyntheses": note_syntheses,
            "unsynthesizedNoteCount": unsynthesized,
            "alerts": self.alerts_service.list_alerts(symbol=symbol, status="active"),
            "fibLevels": fib.get("levels", []) if fib else [],
            "screening": {
                "score": screening.get("score"),
                "upsidePct": screening.get("upsidePct"),
                "flags": screening.get("flags", []),
                "fibDistancePct": screening.get("fibDistancePct"),
            },
            "fundamentals": enrichment.get("fundamentals", {}),
            "recentNews": enrichment.get("recentNews", []),
            "holding": holding,
        }

    def _holding_with_weight(self, symbol: str) -> dict[str, Any] | None:
        holdings = self.holdings_service.list_holdings()
        total_market_value = sum(
            holding["marketValue"] for holding in holdings if holding.get("marketValue")
        )
        holding = self.holdings_service.get_holding(symbol)
        if holding is None:
            return None
        if holding.get("marketValue") and total_market_value:
            holding = {**holding, "weightPct": round(holding["marketValue"] / total_market_value * 100, 2)}
        return holding

    def _save_assessment(
        self,
        symbol: str,
        result: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        factors_json = json.dumps(result.get("factors", []))
        synthesis_json = json.dumps(result.get("noteSynthesis", {}))
        with get_connection() as conn:
            previous = conn.execute(
                """
                SELECT action, confidence FROM assessments
                WHERE symbol = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (symbol,),
            ).fetchone()
            cursor = conn.execute(
                """
                INSERT INTO assessments (
                    symbol, action, confidence, rationale, factors,
                    note_synthesis, trading_recommendation, provider
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    result["action"],
                    result["confidence"],
                    result["rationale"],
                    factors_json,
                    synthesis_json,
                    None,
                    result["provider"],
                ),
            )
            self._record_recommendation_change(conn, symbol, previous, result)
            self._trim_assessment_history(conn, symbol)
            conn.commit()
            row = conn.execute(
                """
                SELECT id, symbol, action, confidence, rationale, factors,
                       note_synthesis, trading_recommendation, provider, created_at
                FROM assessments WHERE id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()

        assessment = self._row_to_assessment(row)
        if result.get("llmFallback"):
            assessment["llmFallback"] = True
            assessment["llmError"] = result.get("llmError")
        assessment["context"] = context
        return assessment

    def _record_recommendation_change(self, conn, symbol: str, previous, result: dict[str, Any]) -> None:
        """Log a changelog row when the discrete action changes vs the prior assessment.

        Skips the very first assessment for a symbol (no prior action to compare).
        """
        if previous is None:
            return
        old_action = previous["action"]
        new_action = result["action"]
        if old_action == new_action:
            return
        conn.execute(
            """
            INSERT INTO recommendation_changelog (
                symbol, old_action, new_action, old_confidence, new_confidence, provider
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                symbol,
                old_action,
                new_action,
                previous["confidence"],
                result["confidence"],
                result.get("provider"),
            ),
        )

    def list_recommendation_changes(self, limit: int = 8) -> list[dict[str, Any]]:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, symbol, old_action, new_action, old_confidence,
                       new_confidence, provider, created_at
                FROM recommendation_changelog
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "symbol": row["symbol"],
                "oldAction": row["old_action"],
                "newAction": row["new_action"],
                "oldConfidence": row["old_confidence"],
                "newConfidence": row["new_confidence"],
                "provider": row["provider"],
                "createdAt": row["created_at"],
            }
            for row in rows
        ]

    def _trim_assessment_history(self, conn, symbol: str) -> None:
        rows = conn.execute(
            """
            SELECT id FROM assessments
            WHERE symbol = ?
            ORDER BY created_at DESC, id DESC
            """,
            (symbol,),
        ).fetchall()
        stale_ids = [row["id"] for row in rows[self.MAX_ASSESSMENTS_PER_SYMBOL :]]
        if not stale_ids:
            return
        placeholders = ",".join("?" * len(stale_ids))
        conn.execute(
            f"DELETE FROM assessments WHERE id IN ({placeholders})",
            stale_ids,
        )

    def _row_to_assessment(self, row) -> dict[str, Any]:
        factors = self._parse_json_field(row["factors"], default=[])
        note_synthesis = self._parse_json_field(row["note_synthesis"], default={})

        return {
            "id": row["id"],
            "symbol": row["symbol"],
            "action": row["action"],
            "confidence": row["confidence"],
            "rationale": row["rationale"],
            "factors": factors,
            "noteSynthesis": note_synthesis,
            "provider": row["provider"],
            "createdAt": row["created_at"],
        }

    @staticmethod
    def _parse_json_field(raw, default):
        if not raw:
            return default
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            if isinstance(default, list):
                return [raw]
            return default
