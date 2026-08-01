"""Unit tests for harvest Loss-score / Trim-score helpers."""

import unittest

from services.harvest_score import (
    fit_harvest_nudge,
    loss_score,
    residual_loss_pct,
    trim_score,
)


class HarvestScoreTests(unittest.TestCase):
    def test_residual_example(self):
        # −50% + 10% 1YT → 45% residual
        self.assertAlmostEqual(residual_loss_pct(-50, 10), 45.0, places=4)
        self.assertAlmostEqual(loss_score(-50, 10), 27.0, places=4)

    def test_missing_1yt_equals_depth(self):
        self.assertAlmostEqual(residual_loss_pct(-50, None), 50.0, places=4)
        self.assertAlmostEqual(loss_score(-50, None), 30.0, places=4)

    def test_trim_thin_upside_near_peak(self):
        parts = trim_score(
            analyst_upside_pct=5,
            personal_upside_pct=8,
            peak_pct=98,
            weight_pct=12,
            buy_qty=0,
            sell_qty=100,
            held=200,
        )
        self.assertGreaterEqual(parts["trimScore"], 40)

    def test_trim_fat_pt_runway(self):
        parts = trim_score(
            analyst_upside_pct=20,
            personal_upside_pct=80,
            peak_pct=70,
            weight_pct=2,
            buy_qty=50,
            sell_qty=0,
            held=100,
        )
        self.assertLessEqual(parts["trimScore"], 5)

    def test_fit_nudge_sell_on_high_loss_score(self):
        nudge, factors = fit_harvest_nudge(
            action="sell",
            gain_pct=-55,
            analyst_upside_pct=5,
            personal_upside_pct=5,
        )
        self.assertGreater(nudge, 0)
        self.assertTrue(any("loss-score" in f.lower() for f in factors))


if __name__ == "__main__":
    unittest.main()
