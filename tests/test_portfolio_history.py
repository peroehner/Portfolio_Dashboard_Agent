"""Unit tests for buy-and-hold past Progress (mocked closes)."""

from __future__ import annotations

import unittest
from datetime import date

import pandas as pd

from services.portfolio_history_service import (
    ath_lookback_start,
    compute_past_progress_from_closes,
    held_positions,
)


def _series(pairs: list[tuple[str, float]]) -> pd.Series:
    idx = pd.to_datetime([d for d, _ in pairs])
    return pd.Series([v for _, v in pairs], index=idx)


class PortfolioHistoryServiceTests(unittest.TestCase):
    def test_held_positions_skips_watch_only(self) -> None:
        holdings = [
            {"symbol": "AAPL", "quantity": 10},
            {"symbol": "MSFT", "quantity": 0},
            {"symbol": "GOOG", "quantity": None},
        ]
        held = held_positions(holdings)
        self.assertEqual([h["symbol"] for h in held], ["AAPL"])

    def test_ath_lookback_uses_oldest_purchase_capped(self) -> None:
        today = date(2026, 8, 4)
        positions = [
            {"symbol": "A", "quantity": 1, "purchaseDate": "2010-01-01"},
            {"symbol": "B", "quantity": 1, "purchaseDate": "2025-06-01"},
        ]
        start = ath_lookback_start(positions, today)
        # Cap at ~5y from today
        self.assertEqual(start, date(2021, 8, 5))

    def test_windows_and_ath_from_closes(self) -> None:
        as_of = date(2026, 8, 4)
        holdings = [
            {"symbol": "AAA", "quantity": 100, "purchaseDate": "2025-01-01"},
            {"symbol": "BBB", "quantity": 50, "purchaseDate": "2025-01-01"},
        ]
        # Dense daily-ish closes
        aaa = []
        bbb = []
        spy = []
        d = date(2025, 1, 2)
        price_a = 10.0
        price_b = 20.0
        price_s = 400.0
        while d <= as_of:
            if d.weekday() < 5:
                aaa.append((d.isoformat(), price_a))
                bbb.append((d.isoformat(), price_b))
                spy.append((d.isoformat(), price_s))
                price_a += 0.05
                price_b += 0.02
                price_s += 0.1
            d = date.fromordinal(d.toordinal() + 1)

        closes = {
            "AAA": _series(aaa),
            "BBB": _series(bbb),
            "SPY": _series(spy),
        }
        # Spike ATH mid-way
        mid = date(2026, 3, 16)
        closes["AAA"].loc[pd.Timestamp(mid)] = 50.0
        closes["BBB"].loc[pd.Timestamp(mid)] = 40.0

        out = compute_past_progress_from_closes(holdings, closes, as_of=as_of)
        self.assertEqual(out["definition"], "current_holdings_buy_hold")
        self.assertIn("1M", out["windows"])
        self.assertIn("3M", out["windows"])
        w1 = out["windows"]["1M"]
        self.assertIsNotNone(w1["returnPct"])
        self.assertIsNotNone(w1["spyReturnPct"])
        self.assertIsNotNone(w1["relativePct"])
        self.assertEqual(w1["coverage"]["heldTotal"], 2)
        self.assertEqual(w1["coverage"]["heldWithPrices"], 2)
        self.assertEqual(len(w1["holdings"]), 2)
        self.assertEqual(
            sum(h["marketValue"] for h in w1["holdings"]),
            w1["valueThen"],
        )

        ath = out["ath"]
        self.assertIsNotNone(ath)
        self.assertEqual(ath["date"], mid.isoformat())
        self.assertGreater(ath["value"], w1["valueNow"])
        self.assertLess(ath["deltaPct"], 0)
        self.assertEqual(len(ath["holdings"]), 2)

    def test_missing_history_reduces_coverage(self) -> None:
        as_of = date(2026, 8, 4)
        holdings = [
            {"symbol": "AAA", "quantity": 10},
            {"symbol": "BBB", "quantity": 10},
        ]
        closes = {
            "AAA": _series(
                [
                    ("2026-05-01", 10.0),
                    ("2026-07-01", 11.0),
                    ("2026-08-04", 12.0),
                ]
            ),
            # BBB has no history
        }
        out = compute_past_progress_from_closes(
            holdings, closes, as_of=as_of, value_now_override=120.0
        )
        w3 = out["windows"].get("3M")
        self.assertIsNotNone(w3)
        self.assertEqual(w3["coverage"]["heldWithPrices"], 1)
        self.assertEqual(w3["coverage"]["heldTotal"], 2)


if __name__ == "__main__":
    unittest.main()
