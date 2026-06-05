import json
from typing import Any

from db.database import get_connection
from services.alerts_service import AlertsService
from services.fib_service import FibService
from services.llm_client import LLMClient
from services.portfolio_service import PortfolioService


class AssessmentService:
    def __init__(self):
        self.portfolio_service = PortfolioService()
        self.alerts_service = AlertsService()
        self.fib_service = FibService()
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
            SELECT id, symbol, action, confidence, rationale, factors, provider, created_at
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

    def _build_context(self, symbol_data: dict[str, Any]) -> dict[str, Any]:
        symbol = symbol_data["symbol"]
        fib = self.fib_service.get_levels(symbol)
        return {
            "symbol": symbol,
            "currentPrice": symbol_data.get("currentPrice"),
            "targetPrice": symbol_data.get("targetPrice"),
            "buyBelow": symbol_data.get("buyBelow"),
            "sellAbove": symbol_data.get("sellAbove"),
            "notes": symbol_data.get("notes", []),
            "alerts": self.alerts_service.list_alerts(symbol=symbol, status="active"),
            "fibLevels": fib.get("levels", []) if fib else [],
        }

    def _save_assessment(
        self,
        symbol: str,
        result: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        factors_json = json.dumps(result.get("factors", []))
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO assessments (symbol, action, confidence, rationale, factors, provider)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    result["action"],
                    result["confidence"],
                    result["rationale"],
                    factors_json,
                    result["provider"],
                ),
            )
            conn.commit()
            row = conn.execute(
                """
                SELECT id, symbol, action, confidence, rationale, factors, provider, created_at
                FROM assessments WHERE id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()

        assessment = self._row_to_assessment(row)
        assessment["context"] = context
        return assessment

    def _row_to_assessment(self, row) -> dict[str, Any]:
        factors = []
        if row["factors"]:
            try:
                factors = json.loads(row["factors"])
            except json.JSONDecodeError:
                factors = [row["factors"]]

        return {
            "id": row["id"],
            "symbol": row["symbol"],
            "action": row["action"],
            "confidence": row["confidence"],
            "rationale": row["rationale"],
            "factors": factors,
            "provider": row["provider"],
            "createdAt": row["created_at"],
        }
