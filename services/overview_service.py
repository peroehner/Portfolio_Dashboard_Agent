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
        total_annual_dividend = 0.0
        total_analyst_target_value = 0.0
        total_personal_target_value = 0.0
        dividend_holdings = 0
        analyst_target_holdings = 0
        personal_target_holdings = 0
        valued_holdings = 0
        holding_symbols = {holding["symbol"] for holding in holdings}

        for holding in holdings:
            if holding.get("marketValue") is not None:
                total_market_value += holding["marketValue"]
                valued_holdings += 1
            if holding.get("totalCost") is not None:
                total_cost += holding["totalCost"]
            annual_dividend = holding.get("annualDividend")
            if annual_dividend is not None:
                total_annual_dividend += annual_dividend
                dividend_holdings += 1
            analyst_target_value = holding.get("analystTargetValue")
            if analyst_target_value is not None:
                total_analyst_target_value += analyst_target_value
                analyst_target_holdings += 1
            personal_target_value = holding.get("personalTargetValue")
            if personal_target_value is not None:
                total_personal_target_value += personal_target_value
                personal_target_holdings += 1

        for holding in holdings:
            if holding.get("marketValue") is not None and total_market_value > 0:
                holding["weightPct"] = round(holding["marketValue"] / total_market_value * 100, 2)

        unrealized_gain = (
            round(total_market_value - total_cost, 2)
            if valued_holdings and total_cost
            else None
        )
        unrealized_gain_pct = (
            round(unrealized_gain / total_cost * 100, 2)
            if unrealized_gain is not None and total_cost
            else None
        )
        total_analyst_target_value = (
            round(total_analyst_target_value, 2) if analyst_target_holdings else None
        )
        total_analyst_upside_pct = (
            round(
                (total_analyst_target_value - total_market_value) / total_market_value * 100,
                2,
            )
            if total_analyst_target_value is not None and total_market_value
            else None
        )
        total_personal_target_value = (
            round(total_personal_target_value, 2) if personal_target_holdings else None
        )
        total_personal_upside_pct = (
            round(
                (total_personal_target_value - total_market_value) / total_market_value * 100,
                2,
            )
            if total_personal_target_value is not None and total_market_value
            else None
        )
        total_projected_roc = None
        total_projected_roc_pct = None
        if total_analyst_target_value is not None and total_market_value:
            annual_dividend_total = total_annual_dividend or 0.0
            analyst_appreciation = total_analyst_target_value - total_market_value
            total_projected_roc = round(annual_dividend_total + analyst_appreciation, 2)
            total_projected_roc_pct = round(
                total_projected_roc / total_market_value * 100,
                2,
            )

        return {
            "symbolCount": len(symbols),
            "holdingCount": len(holdings),
            "watchlistOnlyCount": len(
                [symbol for symbol in symbols if symbol["symbol"] not in holding_symbols]
            ),
            "totalMarketValue": round(total_market_value, 2) if valued_holdings else None,
            "totalCostBasis": round(total_cost, 2) if total_cost else None,
            "unrealizedGain": unrealized_gain,
            "unrealizedGainPct": unrealized_gain_pct,
            "totalAnnualDividend": (
                round(total_annual_dividend, 2) if dividend_holdings else None
            ),
            "totalAnalystTargetValue": total_analyst_target_value,
            "totalAnalystUpsidePct": total_analyst_upside_pct,
            "totalPersonalTargetValue": total_personal_target_value,
            "totalPersonalUpsidePct": total_personal_upside_pct,
            "totalProjectedRoc": total_projected_roc,
            "totalProjectedRocPct": total_projected_roc_pct,
            "activeAlerts": len(alerts),
            "alerts": alerts[:5],
            "latestAssessments": assessments,
            "holdings": holdings,
            "symbols": symbols,
        }
