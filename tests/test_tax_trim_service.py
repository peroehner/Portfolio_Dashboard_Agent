"""Unit tests for Tax & Trim allocation helpers."""

import unittest

from services.tax_trim_service import allocate_winner_trims, sell_threshold_price


class TaxTrimAllocateTests(unittest.TestCase):
    def test_match_loss_caps_to_loss_pool(self):
        selected = [
            {
                "symbol": "AAA",
                "trimScore": 40,
                "netGainsMax": 10_000,
                "gainPerShare": 10.0,
                "sellQtyMax": 1000,
                "execPrice": 100.0,
                "currentPrice": 100.0,
            },
            {
                "symbol": "BBB",
                "trimScore": 30,
                "netGainsMax": 10_000,
                "gainPerShare": 10.0,
                "sellQtyMax": 1000,
                "execPrice": 100.0,
                "currentPrice": 100.0,
            },
        ]
        result = allocate_winner_trims(selected, loss_pool_amount=5_000, match_loss_pool=True)
        self.assertLessEqual(result["offsetGain"], 5_000 + 1e-6)
        self.assertAlmostEqual(result["allocTarget"], 5_000, places=2)
        self.assertTrue(result["picks"])

    def test_match_off_uses_full_trim_pool(self):
        selected = [
            {
                "symbol": "AAA",
                "trimScore": 40,
                "netGainsMax": 2_000,
                "gainPerShare": 10.0,
                "sellQtyMax": 200,
                "execPrice": 50.0,
                "currentPrice": 50.0,
            }
        ]
        result = allocate_winner_trims(selected, loss_pool_amount=50_000, match_loss_pool=False)
        self.assertAlmostEqual(result["allocTarget"], 2_000, places=2)
        self.assertAlmostEqual(result["offsetGain"], 2_000, places=2)

    def test_sell_threshold_weighted_average(self):
        row = {
            "tradeBelowPrice": 90,
            "tradeBelowShares": -10,
            "tradeAbovePrice": 110,
            "tradeAboveShares": -30,
        }
        # (90*10 + 110*30) / 40 = 105
        self.assertAlmostEqual(sell_threshold_price(row), 105.0, places=4)


if __name__ == "__main__":
    unittest.main()
