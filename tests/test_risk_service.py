"""Unit tests for the Risk agent — volume validation of chart patterns (Phase 2).

Pure-function tests with synthetic DataFrames and hand-built volume profiles so
the verdict logic is exercised deterministically (no network, no DB).
"""
import unittest

import numpy as np
import pandas as pd

import services.risk_service as risk
from services.risk_service import validate_pattern, validate_patterns


def _df(prices, volumes):
    idx = pd.date_range("2024-01-01", periods=len(prices), freq="D")
    df = pd.DataFrame(
        {
            "Close": prices,
            "High": [p * 1.01 for p in prices],
            "Low": [p * 0.99 for p in prices],
            "Volume": volumes,
        },
        index=idx,
    )
    dates = [d.strftime("%Y-%m-%d") for d in idx]
    return df, dates


def _profile(bins):
    return {"bins": bins, "poc": None}


def _double_bottom(dates, *, status, key=105.0, bottom=95.0):
    return {
        "name": "Double Bottom",
        "type": "bullish",
        "status": status,
        "confidence": 0.7,
        "startDate": dates[0],
        "endDate": dates[-3],
        "keyLevel": {"label": "neckline", "price": key},
        "target": key + (key - bottom),
        "points": [
            {"date": dates[0], "price": bottom, "role": "Bottom"},
            {"date": dates[len(dates) // 2], "price": key, "role": "Neckline"},
            {"date": dates[-3], "price": bottom + 1, "role": "Bottom"},
        ],
    }


class ValidatePatternTests(unittest.TestCase):
    def test_strong_confirmed_double_bottom(self):
        # Rising into a confirmed breakout, surge on the last bars, demand at the low.
        prices = list(np.linspace(100, 95, 15)) + list(np.linspace(95, 110, 25))
        volumes = [1_000_000] * 37 + [4_000_000] * 3
        df, dates = _df(prices, volumes)
        profile = _profile([
            {"low": 94.0, "high": 96.0, "volume": 1_000_000},
            {"low": 104.0, "high": 106.0, "volume": 300_000},
        ])
        v = validate_pattern(_double_bottom(dates, status="confirmed"), df, profile, 110.0)
        self.assertEqual(v["verdict"], "confirmed")
        self.assertTrue(v["volumeConfirmed"])
        self.assertGreaterEqual(v["breakoutRvol"], 1.3)

    def test_weak_demand_bottom_is_vetoed(self):
        # The motivating example: a bottom where almost no volume traded.
        prices = list(np.linspace(110, 95, 25)) + list(np.linspace(95, 97, 15))
        volumes = [800_000] * 40
        df, dates = _df(prices, volumes)
        profile = _profile([
            {"low": 94.0, "high": 96.0, "volume": 200_000},   # thin at the bottom
            {"low": 108.0, "high": 110.0, "volume": 1_000_000},  # POC up high
        ])
        v = validate_pattern(_double_bottom(dates, status="forming"), df, profile, 97.0)
        self.assertEqual(v["verdict"], "veto")
        self.assertLess(v["score"], 0.40)
        self.assertTrue(any("low-volume" in r for r in v["reasons"]))

    def test_confirmed_break_on_weak_volume_is_not_confirmed(self):
        prices = list(np.linspace(100, 95, 15)) + list(np.linspace(95, 108, 25))
        volumes = [1_000_000] * 37 + [200_000] * 3  # break fizzles on light volume
        df, dates = _df(prices, volumes)
        profile = _profile([
            {"low": 94.0, "high": 96.0, "volume": 600_000},   # medium node
            {"low": 104.0, "high": 106.0, "volume": 1_000_000},
        ])
        v = validate_pattern(_double_bottom(dates, status="confirmed"), df, profile, 108.0)
        self.assertFalse(v["volumeConfirmed"])
        self.assertIn(v["verdict"], ("weak", "veto"))
        self.assertLess(v["breakoutRvol"], 1.0)

    def test_forming_with_decent_context_is_pending_not_confirmed(self):
        prices = list(np.linspace(100, 95, 20)) + list(np.linspace(95, 99, 20))
        volumes = [1_000_000] * 40
        df, dates = _df(prices, volumes)
        profile = _profile([
            {"low": 94.0, "high": 96.0, "volume": 900_000},
            {"low": 98.0, "high": 100.0, "volume": 1_000_000},
        ])
        v = validate_pattern(_double_bottom(dates, status="forming"), df, profile, 99.0)
        self.assertIn(v["verdict"], ("pending", "weak"))
        self.assertFalse(v["volumeConfirmed"])


class ValidatePatternsTests(unittest.TestCase):
    def test_downgrade_keeps_veto_pattern_with_validation(self):
        prices = list(np.linspace(110, 95, 25)) + list(np.linspace(95, 97, 15))
        df, dates = _df(prices, [800_000] * 40)
        profile = _profile([
            {"low": 94.0, "high": 96.0, "volume": 200_000},
            {"low": 108.0, "high": 110.0, "volume": 1_000_000},
        ])
        pattern = _double_bottom(dates, status="forming")
        orig_action = risk.ACTION
        try:
            risk.ACTION = "downgrade"
            out = validate_patterns([pattern], df, profile, 97.0)
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0]["validation"]["verdict"], "veto")
        finally:
            risk.ACTION = orig_action

    def test_veto_mode_drops_veto_pattern(self):
        prices = list(np.linspace(110, 95, 25)) + list(np.linspace(95, 97, 15))
        df, dates = _df(prices, [800_000] * 40)
        profile = _profile([
            {"low": 94.0, "high": 96.0, "volume": 200_000},
            {"low": 108.0, "high": 110.0, "volume": 1_000_000},
        ])
        pattern = _double_bottom(dates, status="forming")
        orig_action = risk.ACTION
        try:
            risk.ACTION = "veto"
            out = validate_patterns([pattern], df, profile, 97.0)
            self.assertEqual(out, [])
        finally:
            risk.ACTION = orig_action


if __name__ == "__main__":
    unittest.main()
