import contextvars
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from db.database import get_connection, get_current_user_id
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
        self.assess_workers = max(1, int(os.environ.get("ASSESS_WORKERS", "6")))

    def _compute_assessment(self, symbol: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """Build context and run the (slow, network-bound) LLM call. No DB writes."""
        symbol = symbol.upper()
        symbol_data = self.portfolio_service.get_symbol(symbol)
        if symbol_data is None:
            raise ValueError(f"Symbol {symbol} not found.")
        context = self._build_context(symbol_data)
        result = self.llm_client.generate_assessment(context)
        return result, context

    def assess_symbol(self, symbol: str) -> dict[str, Any]:
        result, context = self._compute_assessment(symbol)
        return self._save_assessment(symbol.upper(), result, context)

    def assess_portfolio(self, symbols: list[str] | None = None) -> list[dict[str, Any]]:
        if symbols:
            symbol_list = [str(symbol).upper() for symbol in symbols]
        else:
            symbol_list = [item["symbol"] for item in self.portfolio_service.list_symbols()]
        if not symbol_list:
            return []

        # The per-symbol LLM call dominates wall time (~15s each on Gemini), so a
        # sequential pass over a full portfolio can take many minutes and makes the
        # UI look stuck. Run the network-bound compute concurrently, then persist
        # serially on this thread (SQLite writes stay single-threaded and ordered).
        computed: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        first_error: Exception | None = None
        workers = min(self.assess_workers, len(symbol_list))
        # Worker threads must see the same current user as this request; copy the
        # context so get_current_user_id() resolves correctly inside the pool.
        ctx = contextvars.copy_context()
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {
                executor.submit(ctx.run, self._compute_assessment, sym): sym
                for sym in symbol_list
            }
            for future, sym in future_map.items():
                try:
                    computed[sym] = future.result()
                except Exception as exc:  # noqa: BLE001 - surfaced/handled below
                    if first_error is None:
                        first_error = exc
                    logging.warning("Assessment compute failed for %s: %s", sym, exc)

        # Preserve the original "unknown symbol -> 404" contract for explicit requests.
        if symbols and isinstance(first_error, ValueError):
            raise first_error

        assessments = []
        for sym in symbol_list:
            if sym not in computed:
                continue
            result, context = computed[sym]
            assessments.append(self._save_assessment(sym, result, context))
        return assessments

    def list_assessments(self, symbol: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        query = """
            SELECT id, symbol, action, confidence, rationale, factors,
                   note_synthesis, trading_recommendation, provider, created_at
            FROM assessments
            WHERE user_id = %s
        """
        params: list[Any] = [get_current_user_id()]
        if symbol:
            query += " AND symbol = %s"
            params.append(symbol.upper())
        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)

        with get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_assessment(row) for row in rows]

    def delete_assessment(self, assessment_id: int, symbol: str | None = None) -> bool:
        query = "DELETE FROM assessments WHERE id = %s AND user_id = %s"
        params: list[Any] = [assessment_id, get_current_user_id()]
        if symbol:
            query += " AND symbol = %s"
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
        user_id = get_current_user_id()
        with get_connection() as conn:
            previous = conn.execute(
                """
                SELECT action, confidence FROM assessments
                WHERE user_id = %s AND symbol = %s
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (user_id, symbol),
            ).fetchone()
            cursor = conn.execute(
                """
                INSERT INTO assessments (
                    user_id, symbol, action, confidence, rationale, factors,
                    note_synthesis, trading_recommendation, provider
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    user_id,
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
            new_id = cursor.fetchone()["id"]
            self._record_recommendation_change(conn, user_id, symbol, previous, result)
            self._trim_assessment_history(conn, user_id, symbol)
            conn.commit()
            row = conn.execute(
                """
                SELECT id, symbol, action, confidence, rationale, factors,
                       note_synthesis, trading_recommendation, provider, created_at
                FROM assessments WHERE id = %s
                """,
                (new_id,),
            ).fetchone()

        assessment = self._row_to_assessment(row)
        if result.get("llmFallback"):
            assessment["llmFallback"] = True
            assessment["llmError"] = result.get("llmError")
        assessment["context"] = context
        return assessment

    def _record_recommendation_change(
        self, conn, user_id: int, symbol: str, previous, result: dict[str, Any]
    ) -> None:
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
                user_id, symbol, old_action, new_action, old_confidence, new_confidence, provider
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                user_id,
                symbol,
                old_action,
                new_action,
                previous["confidence"],
                result["confidence"],
                result.get("provider"),
            ),
        )

    def list_recommendation_changes(self, limit: int = 8) -> list[dict[str, Any]]:
        user_id = get_current_user_id()
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, symbol, old_action, new_action, old_confidence,
                       new_confidence, provider, created_at
                FROM recommendation_changelog
                WHERE user_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (user_id, limit),
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

    def _trim_assessment_history(self, conn, user_id: int, symbol: str) -> None:
        rows = conn.execute(
            """
            SELECT id FROM assessments
            WHERE user_id = %s AND symbol = %s
            ORDER BY created_at DESC, id DESC
            """,
            (user_id, symbol),
        ).fetchall()
        stale_ids = [row["id"] for row in rows[self.MAX_ASSESSMENTS_PER_SYMBOL :]]
        if not stale_ids:
            return
        placeholders = ",".join(["%s"] * len(stale_ids))
        conn.execute(
            f"DELETE FROM assessments WHERE user_id = %s AND id IN ({placeholders})",
            [user_id, *stale_ids],
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
