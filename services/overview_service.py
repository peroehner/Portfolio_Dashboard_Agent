from typing import Any

from services.alerts_service import AlertsService
from services.assessment_service import AssessmentService
from services.holdings_service import HoldingsService
from services.portfolio_service import PortfolioService


class OverviewService:
    def __init__(self):
        self.portfolio_service = PortfolioService()
        self.holdings_service = HoldingsService()
        self.alerts_service = AlertsService()
        self.assessment_service = AssessmentService()

    def get_overview(self) -> dict[str, Any]:
        symbols = self.portfolio_service.list_symbols()
        holdings = self.holdings_service.list_holdings()
        alerts = self.alerts_service.list_alerts(status="active")
        assessments = self.assessment_service.list_assessments(limit=5)

        total_market_value = 0.0
        total_cost = 0.0
        valued_holdings = 0

        for holding in holdings:
            if holding.get("marketValue") is not None:
                total_market_value += holding["marketValue"]
                valued_holdings += 1
            if holding.get("totalCost") is not None:
                total_cost += holding["totalCost"]

        for holding in holdings:
            if holding.get("marketValue") is not None and total_market_value > 0:
                holding["weightPct"] = round(holding["marketValue"] / total_market_value * 100, 2)

        return {
            "symbolCount": len(symbols),
            "holdingCount": len(holdings),
            "totalMarketValue": round(total_market_value, 2) if valued_holdings else None,
            "totalCostBasis": round(total_cost, 2) if total_cost else None,
            "unrealizedGain": (
                round(total_market_value - total_cost, 2)
                if valued_holdings and total_cost
                else None
            ),
            "activeAlerts": len(alerts),
            "alerts": alerts[:5],
            "latestAssessments": assessments,
            "holdings": holdings,
            "symbols": symbols,
        }
