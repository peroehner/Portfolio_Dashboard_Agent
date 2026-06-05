from typing import Any

from services.alerts_service import AlertsService
from services.assessment_service import AssessmentService
from services.fib_service import FibService
from services.holdings_service import HoldingsService
from services.portfolio_service import PortfolioService
from services.screening_service import ScreeningService


class InspectorService:
    def __init__(self):
        self.portfolio_service = PortfolioService()
        self.holdings_service = HoldingsService()
        self.alerts_service = AlertsService()
        self.assessment_service = AssessmentService()
        self.fib_service = FibService()
        self.screening_service = ScreeningService()

    def inspect(self, symbol: str) -> dict[str, Any] | None:
        symbol = symbol.upper()
        symbol_data = self.portfolio_service.get_symbol(symbol)
        if symbol_data is None:
            return None

        price = symbol_data.get("currentPrice")
        fib = self.fib_service.get_levels(symbol)
        nearest = (
            self.fib_service.nearest_level(symbol, price, self.screening_service.fib_proximity_pct)
            if price is not None
            else None
        )
        screen_row = self.screening_service._score_symbol(
            {**symbol_data, "notes": symbol_data.get("notes", [])}
        )
        assessments = self.assessment_service.list_assessments(symbol=symbol, limit=3)

        return {
            "symbol": symbol,
            "quote": symbol_data,
            "holding": self.holdings_service.get_holding(symbol),
            "alerts": self.alerts_service.list_alerts(symbol=symbol, status="active"),
            "fib": fib,
            "nearestFib": nearest,
            "screening": screen_row,
            "assessments": assessments,
        }
