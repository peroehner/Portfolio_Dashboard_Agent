"""Unit tests for Signal Record insight + weekly self-assessment helpers."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from services.track_record_insight import build_insight
from services.signal_record_weekly_assessment_service import (
    current_iso_week,
    should_run_this_week,
    weekly_assessment_enabled,
)


def _sample_summary(*, high_cal=55.7, med_cal=67.1) -> dict:
    return {
        "overall": {
            "wins": 69,
            "losses": 46,
            "neutrals": 1,
            "count": 116,
            "hitRate": 60.0,
            "calibratedHitRate": 60.6,
            "avgReturn": 1.2,
            "avgReturnAdj": 0.7,
        },
        "byLabel": [
            {
                "kind": "recommendation",
                "label": "sell",
                "wins": 2,
                "losses": 1,
                "neutrals": 2,
                "count": 5,
                "hitRate": 66.7,
                "calibratedHitRate": 68.5,
                "avgReturn": -0.27,
                "avgReturnAdj": 0.27,
            },
            {
                "kind": "recommendation",
                "label": "buy",
                "wins": 22,
                "losses": 15,
                "neutrals": 11,
                "count": 48,
                "hitRate": 59.5,
                "calibratedHitRate": 60.0,
                "avgReturn": 1.67,
                "avgReturnAdj": 1.67,
            },
            {
                "kind": "pattern",
                "label": "Double Top",
                "wins": 3,
                "losses": 2,
                "count": 5,
                "hitRate": 60.0,
                "calibratedHitRate": 60.0,
                "avgReturn": -9.24,
                "avgReturnAdj": 9.24,
            },
            {
                "kind": "confluence",
                "label": "bullish",
                "wins": 6,
                "losses": 1,
                "neutrals": 4,
                "count": 11,
                "hitRate": 85.7,
                "calibratedHitRate": 85.7,
                "avgReturn": 3.32,
                "avgReturnAdj": 3.32,
            },
            {
                "kind": "confluence",
                "label": "bearish",
                "wins": 7,
                "losses": 1,
                "neutrals": 1,
                "count": 9,
                "hitRate": 87.5,
                "calibratedHitRate": 87.5,
                "avgReturn": -8.99,
                "avgReturnAdj": 8.99,
            },
        ],
        "byConfidence": [
            {
                "confidence": "high",
                "wins": 5,
                "losses": 4,
                "neutrals": 6,
                "count": 15,
                "hitRate": 55.6,
                "calibratedHitRate": high_cal,
                "avgReturn": 0.0,
                "avgReturnAdj": 0.18,
            },
            {
                "confidence": "medium",
                "wins": 9,
                "losses": 5,
                "neutrals": 44,
                "count": 58,
                "hitRate": 64.3,
                "calibratedHitRate": med_cal,
                "avgReturn": 1.55,
                "avgReturnAdj": 0.37,
            },
            {
                "confidence": "low",
                "wins": 10,
                "losses": 7,
                "neutrals": 26,
                "count": 43,
                "hitRate": 58.8,
                "calibratedHitRate": 59.9,
                "avgReturn": 2.37,
                "avgReturnAdj": 1.33,
            },
        ],
    }


class TrackRecordInsightTests(unittest.TestCase):
    def test_flags_high_conf_trailing_medium(self) -> None:
        insight = build_insight(_sample_summary())
        self.assertEqual(insight["tone"], "warn")
        self.assertTrue(any("High Conf" in d for d in insight["discount"]))
        self.assertTrue(any("Medium-Conf" in u for u in insight["use"]))
        self.assertTrue(
            any("Tech bias" in t or "SAI overall" in t or "SAI Sell" in t for t in insight["trust"])
        )

    def test_no_high_conf_flag_when_high_leads(self) -> None:
        insight = build_insight(_sample_summary(high_cal=72.0, med_cal=60.0))
        self.assertFalse(any("High Conf" in d and "trails" in d for d in insight["discount"]))

    def test_thin_book_is_empty(self) -> None:
        insight = build_insight(
            {
                "overall": {
                    "wins": 2,
                    "losses": 1,
                    "count": 3,
                    "hitRate": 66.7,
                    "calibratedHitRate": 66.7,
                },
                "byLabel": [],
                "byConfidence": [],
            }
        )
        self.assertEqual(insight["tone"], "empty")


class WeeklyAssessmentGateTests(unittest.TestCase):
    def test_enabled_by_default(self) -> None:
        with patch.dict("os.environ", {"SIGNAL_RECORD_WEEKLY_ASSESSMENT": "1"}):
            self.assertTrue(weekly_assessment_enabled())

    def test_disabled_via_env(self) -> None:
        with patch.dict("os.environ", {"SIGNAL_RECORD_WEEKLY_ASSESSMENT": "0"}):
            self.assertFalse(weekly_assessment_enabled())
            self.assertFalse(should_run_this_week())

    def test_iso_week_format(self) -> None:
        week = current_iso_week()
        self.assertRegex(week, r"^\d{4}-W\d{2}$")


if __name__ == "__main__":
    unittest.main()
