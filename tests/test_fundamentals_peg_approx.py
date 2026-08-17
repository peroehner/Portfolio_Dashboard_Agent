"""Fundamentals helpers — PEG approximation when Yahoo omits pegRatio."""

import unittest

from services.fundamentals_service import FundamentalsService


class ApproxPegTests(unittest.TestCase):
    def test_approx_from_trailing_pe_and_growth_fraction(self):
        data = {
            "valuation": {"trailingPe": 20.0, "forwardPe": 18.0},
            "growthProfitability": {"earningsGrowth": 0.15},
        }
        out = FundamentalsService._with_approx_peg(data)
        self.assertAlmostEqual(out["valuation"]["pegRatio"], 20.0 / 15.0, places=4)
        self.assertTrue(out["valuation"]["pegRatioApprox"])
        self.assertEqual(out["valuation"]["pegRatioApproxFrom"], "trailingPe")

    def test_prefers_forward_pe_when_trailing_missing(self):
        data = {
            "valuation": {"forwardPe": 12.0},
            "growthProfitability": {"earningsGrowth": 0.20},
        }
        out = FundamentalsService._with_approx_peg(data)
        self.assertAlmostEqual(out["valuation"]["pegRatio"], 12.0 / 20.0, places=4)
        self.assertEqual(out["valuation"]["pegRatioApproxFrom"], "forwardPe")

    def test_skips_when_yahoo_peg_present(self):
        data = {
            "valuation": {"pegRatio": 1.1, "trailingPe": 20.0},
            "growthProfitability": {"earningsGrowth": 0.15},
        }
        out = FundamentalsService._with_approx_peg(data)
        self.assertEqual(out["valuation"]["pegRatio"], 1.1)
        self.assertNotIn("pegRatioApprox", out["valuation"])

    def test_skips_negative_pe_or_growth(self):
        data = {
            "valuation": {"forwardPe": -40.0},
            "growthProfitability": {"earningsGrowth": 0.5},
        }
        out = FundamentalsService._with_approx_peg(data)
        self.assertNotIn("pegRatio", out["valuation"])


if __name__ == "__main__":
    unittest.main()
