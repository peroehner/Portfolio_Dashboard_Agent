"""Preferences merge — Portfolio Fit + Tax & Trim + Buy/Sell Plan."""

import json
import unittest
from unittest.mock import MagicMock, patch

from services.preferences_service import PreferencesService


class PreferencesTaxTrimTests(unittest.TestCase):
    def test_merge_tax_trim_preserves_portfolio_fit(self):
        svc = PreferencesService()
        existing = {
            "portfolioFit": {
                "targetAnnualDividend": 12000,
                "volatilityPreference": "moderate",
                "maxSingleNameWeightPct": 15,
                "sectorCapPct": None,
                "taxLotPreference": None,
                "filterSetBias": None,
            },
            "other": "keep-me",
        }
        conn = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        conn.execute.return_value.fetchone.return_value = {
            "preferences_json": existing,
        }

        with patch("services.preferences_service.get_connection", return_value=conn):
            with patch("services.preferences_service.get_current_user_id", return_value=1):
                result = svc.update(
                    {
                        "taxTrim": {
                            "pricingMode": "threshold",
                            "lossScoreThreshold": 18,
                            "trimScoreThreshold": 22,
                            "matchLossPool": False,
                        }
                    }
                )

        self.assertEqual(result["taxTrim"]["lossScoreThreshold"], 18)
        self.assertEqual(result["taxTrim"]["pricingMode"], "threshold")
        self.assertFalse(result["taxTrim"]["matchLossPool"])
        self.assertEqual(result["portfolioFit"]["targetAnnualDividend"], 12000)

        written = conn.execute.call_args_list[-1][0][1][0]
        blob = json.loads(written)
        self.assertEqual(blob["other"], "keep-me")
        self.assertEqual(blob["taxTrim"]["trimScoreThreshold"], 22)

    def test_get_defaults_tax_trim(self):
        svc = PreferencesService()
        conn = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        conn.execute.return_value.fetchone.return_value = {"preferences_json": {}}

        with patch("services.preferences_service.get_connection", return_value=conn):
            with patch("services.preferences_service.get_current_user_id", return_value=1):
                result = svc.get()

        self.assertIsNone(result["taxTrim"])
        self.assertIsNone(result["tradePlan"])
        self.assertEqual(result["tickerSegments"], {})

    def test_merge_trade_plan_preserves_tax_trim(self):
        svc = PreferencesService()
        existing = {
            "taxTrim": {
                "pricingMode": "current",
                "lossScoreThreshold": 12,
                "trimScoreThreshold": 8,
                "matchLossPool": True,
            },
            "other": "keep-me",
        }
        conn = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        conn.execute.return_value.fetchone.return_value = {
            "preferences_json": existing,
        }

        with patch("services.preferences_service.get_connection", return_value=conn):
            with patch("services.preferences_service.get_current_user_id", return_value=1):
                result = svc.update(
                    {
                        "tradePlan": {
                            "pricingMode": "threshold",
                            "qualificationMode": "score",
                            "sellProxThreshold": 12,
                            "buyProxThreshold": 8,
                            "sellScoreThreshold": 35,
                            "buyScoreThreshold": 55,
                            "sellBudget": 25000,
                            "buyBudget": 10000,
                            "listMode": "buy",
                        }
                    }
                )

        self.assertEqual(result["tradePlan"]["sellBudget"], 25000)
        self.assertEqual(result["tradePlan"]["qualificationMode"], "score")
        self.assertEqual(result["tradePlan"]["listMode"], "buy")
        self.assertEqual(result["taxTrim"]["lossScoreThreshold"], 12)

        written = conn.execute.call_args_list[-1][0][1][0]
        blob = json.loads(written)
        self.assertEqual(blob["other"], "keep-me")
        self.assertEqual(blob["tradePlan"]["buyBudget"], 10000)
        self.assertEqual(blob["taxTrim"]["trimScoreThreshold"], 8)


if __name__ == "__main__":
    unittest.main()
