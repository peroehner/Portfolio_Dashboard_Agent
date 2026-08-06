"""Preferences merge — Portfolio Fit + Tax & Trim."""

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


if __name__ == "__main__":
    unittest.main()
