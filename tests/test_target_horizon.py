"""Unit tests for PT Horizon normalization."""

from __future__ import annotations

import unittest

from services.portfolio_service import PortfolioService


class TargetHorizonNormalizeTests(unittest.TestCase):
    def test_empty_clears(self) -> None:
        self.assertIsNone(PortfolioService._normalize_horizon_years(None))
        self.assertIsNone(PortfolioService._normalize_horizon_years(""))
        self.assertIsNone(PortfolioService._normalize_horizon_years(0))
        self.assertIsNone(PortfolioService._normalize_horizon_years(-1))

    def test_clamps_and_rounds(self) -> None:
        self.assertEqual(PortfolioService._normalize_horizon_years(3), 3.0)
        self.assertEqual(PortfolioService._normalize_horizon_years("2.56"), 2.6)
        self.assertEqual(PortfolioService._normalize_horizon_years(0.1), 0.2)  # floor 0.25 → 1dp
        self.assertEqual(PortfolioService._normalize_horizon_years(100), 30.0)

    def test_normalize_symbol_input_aliases(self) -> None:
        svc = PortfolioService()
        out = svc._normalize_symbol_input({"targetHorizonYears": "5"})
        self.assertEqual(out["target_horizon_years"], 5.0)
        out2 = svc._normalize_symbol_input({"ptHorizonYears": 1.5})
        self.assertEqual(out2["target_horizon_years"], 1.5)


if __name__ == "__main__":
    unittest.main()
