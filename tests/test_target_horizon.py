"""Unit tests for PT Horizon date parsing and progress-laggard gate."""

from __future__ import annotations

import unittest
from datetime import date

from services.target_horizon import (
    format_horizon_date,
    is_progress_laggard,
    parse_horizon_date,
    progress_lag,
    years_remaining,
)


class TargetHorizonParseTests(unittest.TestCase):
    def test_empty(self) -> None:
        self.assertIsNone(parse_horizon_date(None))
        self.assertIsNone(parse_horizon_date(""))
        self.assertIsNone(parse_horizon_date("nope"))

    def test_year_and_quarter(self) -> None:
        self.assertEqual(parse_horizon_date("2030"), date(2030, 12, 31))
        self.assertEqual(parse_horizon_date("Q2-2027"), date(2027, 6, 30))
        self.assertEqual(parse_horizon_date("2027-Q3"), date(2027, 9, 30))
        self.assertEqual(parse_horizon_date("2027-06-15"), date(2027, 6, 15))

    def test_quarter_input_is_case_insensitive(self) -> None:
        # Lower/upper/mixed-case quarter labels (and separators) all normalize to
        # the same end date — editing "Q2-2027" must work as well as "q2-2027".
        expected = date(2027, 6, 30)
        for text in ("q2-2027", "Q2-2027", "Q2 2027", "q2 2027", "2027-q2", "2027-Q2"):
            self.assertEqual(parse_horizon_date(text), expected, text)

    def test_format(self) -> None:
        self.assertEqual(format_horizon_date(date(2030, 12, 31)), "2030")
        self.assertEqual(format_horizon_date(date(2027, 6, 30)), "Q2-2027")
        self.assertEqual(format_horizon_date(date(2027, 6, 15)), "2027-06-15")

    def test_years_remaining(self) -> None:
        today = date(2026, 9, 20)
        self.assertEqual(years_remaining(date(2027, 9, 20), today=today), 1.0)


class ProgressLaggardTests(unittest.TestCase):
    def test_not_yet_halfway(self) -> None:
        # 40% elapsed, 0% price progress → lag 40pp but gate requires ≥50% elapsed
        detail = progress_lag(
            basis_at=date(2024, 1, 1),
            horizon_at=date(2026, 1, 1),
            basis_price=100,
            target_price=200,
            current_price=100,
            today=date(2024, 10, 19),  # ~40% of 731 days
        )
        assert detail is not None
        self.assertLess(detail["elapsed"], 0.5)
        self.assertFalse(detail["isLaggard"])
        self.assertFalse(
            is_progress_laggard(
                basis_at=date(2024, 1, 1),
                horizon_at=date(2026, 1, 1),
                basis_price=100,
                target_price=200,
                current_price=100,
                today=date(2024, 10, 19),
            )
        )

    def test_laggard_when_behind_linear(self) -> None:
        # 75% elapsed, only 20% of gap closed → lag 55pp ≥ 30pp
        detail = progress_lag(
            basis_at=date(2024, 1, 1),
            horizon_at=date(2028, 1, 1),
            basis_price=100,
            target_price=200,
            current_price=120,
            today=date(2027, 1, 1),  # 75% of window
        )
        assert detail is not None
        self.assertGreaterEqual(detail["elapsed"], 0.5)
        self.assertGreaterEqual(detail["lag"], 0.30)
        self.assertTrue(detail["isLaggard"])

    def test_on_track_not_laggard(self) -> None:
        # 75% elapsed, 70% of gap closed → lag 5pp
        detail = progress_lag(
            basis_at=date(2024, 1, 1),
            horizon_at=date(2028, 1, 1),
            basis_price=100,
            target_price=200,
            current_price=170,
            today=date(2027, 1, 1),
        )
        assert detail is not None
        self.assertFalse(detail["isLaggard"])


if __name__ == "__main__":
    unittest.main()
