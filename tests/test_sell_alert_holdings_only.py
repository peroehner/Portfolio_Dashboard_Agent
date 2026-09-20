"""Trade@Above (sell) alerts must not fire for watch-only symbols.

You can only sell what you already hold, so sell-side Above alerts are suppressed
when nothing is held. A positive planned quantity (a buy/add on a breakout) is a
buy intent and stays enabled even for a watch. These exercise
``AlertsService._check_thresholds`` with the DB touchpoints (holding lookup and
alert insert) stubbed out.
"""

import unittest
from unittest import mock

from services.alerts_service import AlertsService


def _run(symbol_data, held_shares):
    """Return the alert types _check_thresholds would create for this input."""
    service = AlertsService()
    created: list[str] = []

    def fake_create(**kwargs):
        created.append(kwargs["alert_type"])
        return {"type": kwargs["alert_type"]}

    with mock.patch.object(
        service, "_holding_context", return_value=(held_shares, None)
    ), mock.patch.object(service, "_create_alert", side_effect=fake_create):
        service._check_thresholds(symbol_data)
    return created


def _above_reached(shares):
    return {
        "symbol": "MRVL",
        "currentPrice": 251.01,
        "tradeBelowPrice": None,
        "tradeBelowShares": None,
        "tradeAbovePrice": 251.01,
        "tradeAboveShares": shares,
    }


class SellAlertHoldingsOnlyTests(unittest.TestCase):
    def test_watch_only_suppresses_sell_above_reached(self):
        created = _run(_above_reached(-50), held_shares=0)
        self.assertNotIn("trade_above", created)

    def test_watch_only_suppresses_sell_above_near(self):
        # 2.7% below the sell level -> "near" (within 5%), still a sell on a watch.
        data = _above_reached(-50)
        data["currentPrice"] = 244.25
        created = _run(data, held_shares=0)
        self.assertNotIn("trade_above_near", created)

    def test_watch_only_suppresses_sell_above_when_no_qty(self):
        # No quantity set -> default direction is Sell, so still suppressed.
        created = _run(_above_reached(None), held_shares=0)
        self.assertNotIn("trade_above", created)

    def test_held_symbol_still_gets_sell_above(self):
        created = _run(_above_reached(-50), held_shares=100)
        self.assertIn("trade_above", created)

    def test_watch_only_planned_add_above_still_fires(self):
        # Positive quantity above the price is a planned BUY on a breakout, which
        # is valid for a watch (you are entering, not selling).
        created = _run(_above_reached(50), held_shares=0)
        self.assertIn("trade_above", created)

    def test_watch_only_buy_below_unaffected(self):
        # Trade@Below (buy the dip) must still fire for watch-only symbols.
        data = {
            "symbol": "MRVL",
            "currentPrice": 95.0,
            "tradeBelowPrice": 100.0,
            "tradeBelowShares": 10,
            "tradeAbovePrice": None,
            "tradeAboveShares": None,
        }
        created = _run(data, held_shares=0)
        self.assertIn("trade_below", created)


if __name__ == "__main__":
    unittest.main()
