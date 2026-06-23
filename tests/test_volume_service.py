"""Unit tests for the volume analytics layer (Phase 0 + Phase 1).

Pure-function tests with synthetic DataFrames — no network, no DB.
"""
import unittest

import numpy as np
import pandas as pd

from services.volume_service import volume_at_price, volume_block, volume_profile


def _frame(close, volume, high=None, low=None):
    n = len(close)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    high = high if high is not None else [c * 1.01 for c in close]
    low = low if low is not None else [c * 0.99 for c in close]
    return pd.DataFrame(
        {"Close": close, "High": high, "Low": low, "Volume": volume}, index=idx
    )


class VolumeBlockTests(unittest.TestCase):
    def test_steady_volume_gives_rvol_near_one(self):
        df = _frame([100.0] * 60, [1_000_000] * 60)
        block = volume_block(df)
        self.assertIsNotNone(block)
        self.assertAlmostEqual(block["rvol"], 1.0, delta=0.05)
        self.assertEqual(block["state"], "normal")
        self.assertEqual(block["avgVolume20"], 1_000_000)

    def test_final_spike_flags_surging(self):
        vol = [1_000_000] * 59 + [3_000_000]
        df = _frame([100.0] * 60, vol)
        block = volume_block(df)
        self.assertGreaterEqual(block["rvol"], 2.0)
        self.assertEqual(block["state"], "surging")

    def test_light_volume_flagged(self):
        vol = [1_000_000] * 59 + [300_000]
        df = _frame([100.0] * 60, vol)
        block = volume_block(df)
        self.assertEqual(block["state"], "light")

    def test_rising_participation_trend(self):
        # Low volume early, high volume in the last ~20 sessions.
        vol = [500_000] * 40 + [1_500_000] * 20
        df = _frame([100.0] * 60, vol)
        block = volume_block(df)
        self.assertEqual(block["trend"], "rising")

    def test_obv_positive_on_uptrend(self):
        close = list(np.linspace(100, 140, 60))
        df = _frame(close, [1_000_000] * 60)
        block = volume_block(df)
        self.assertIsNotNone(block["obvSlopePct"])
        self.assertGreater(block["obvSlopePct"], 0)

    def test_missing_volume_column_returns_none(self):
        df = _frame([100.0] * 60, [1_000_000] * 60).drop(columns=["Volume"])
        self.assertIsNone(volume_block(df))

    def test_all_zero_volume_returns_none(self):
        df = _frame([100.0] * 60, [0] * 60)
        self.assertIsNone(volume_block(df))


class VolumeProfileTests(unittest.TestCase):
    def test_poc_lands_on_heaviest_price(self):
        # Most days trade tightly around 50 with huge volume; a few spikes to 100
        # carry little volume. POC must sit near 50, not 100.
        close = [50.0] * 50 + [100.0] * 5
        high = [50.5] * 50 + [100.5] * 5
        low = [49.5] * 50 + [99.5] * 5
        volume = [2_000_000] * 50 + [100_000] * 5
        df = _frame(close, volume, high=high, low=low)
        profile = volume_profile(df, lookback=100, bins=20)
        self.assertIsNotNone(profile)
        self.assertLess(abs(profile["poc"] - 50.0), 5.0)
        self.assertLessEqual(profile["val"], profile["poc"])
        self.assertGreaterEqual(profile["vah"], profile["poc"])

    def test_value_area_within_range(self):
        close = list(np.linspace(80, 120, 120))
        df = _frame(close, [1_000_000] * 120)
        profile = volume_profile(df, lookback=120, bins=24)
        self.assertGreaterEqual(profile["val"], profile["rangeLow"] - 0.01)
        self.assertLessEqual(profile["vah"], profile["rangeHigh"] + 0.01)
        self.assertEqual(len(profile["bins"]), 24)

    def test_price_node_classification(self):
        close = [50.0] * 50 + [100.0] * 5
        high = [50.5] * 50 + [100.5] * 5
        low = [49.5] * 50 + [99.5] * 5
        volume = [2_000_000] * 50 + [100_000] * 5
        df = _frame(close, volume, high=high, low=low)
        profile = volume_profile(df, lookback=100, bins=20)
        # A price at the heavy 50 zone is a high-volume node; the thin 100 zone is low.
        heavy = volume_at_price(profile["bins"], 50.0)
        thin = volume_at_price(profile["bins"], 100.0)
        self.assertEqual(heavy["node"], "high")
        self.assertIn(thin["node"], ("low", "gap"))
        self.assertLess(thin["pctOfPoc"], heavy["pctOfPoc"])

    def test_price_outside_range_is_gap(self):
        df = _frame([50.0] * 60, [1_000_000] * 60)
        profile = volume_profile(df, lookback=60, bins=20)
        node = volume_at_price(profile["bins"], 500.0)
        self.assertEqual(node["node"], "gap")


if __name__ == "__main__":
    unittest.main()
