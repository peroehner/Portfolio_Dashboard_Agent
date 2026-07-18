"""Unit tests for 1YT (screener upside) alert enrichment."""
import unittest
from unittest.mock import MagicMock, patch

from services.alerts_service import AlertsService
from services.assessment_overlay_service import AssessmentOverlayService
from services.one_yt_context import (
    atr_units,
    build_one_yt_context,
    categorize_one_yt,
    format_one_yt_message,
    lead_pattern,
    portfolio_median_upside,
    stance_hint_for_one_yt,
    upside_pct,
    vs_median_multiple,
)


class OneYtMathTests(unittest.TestCase):
    def test_upside_and_median(self):
        self.assertEqual(upside_pct(100, 130), 30.0)
        book = {
            "A": {"currentPrice": 100, "analystTarget1y": 110},  # 10%
            "B": {"currentPrice": 100, "analystTarget1y": 140},  # 40%
            "C": {"currentPrice": 100, "analystTarget1y": 120},  # 20%
        }
        self.assertEqual(portfolio_median_upside(book), 20.0)
        self.assertEqual(vs_median_multiple(60.0, 20.0), 3.0)

    def test_atr_units(self):
        self.assertEqual(atr_units(40.0, 2.0), 20.0)

    def test_lead_pattern_prefers_confirmed(self):
        lead = lead_pattern(
            [
                {
                    "name": "Triangle",
                    "type": "bullish",
                    "confidence": 0.9,
                    "validation": {"verdict": "pending", "adjustedConfidence": 0.9},
                },
                {
                    "name": "Double Bottom",
                    "type": "bullish",
                    "confidence": 0.7,
                    "validation": {"verdict": "confirmed", "adjustedConfidence": 0.7},
                },
            ]
        )
        self.assertEqual(lead["name"], "Double Bottom")
        self.assertEqual(lead["verdict"], "confirmed")

    def test_stance_chance_vs_risk(self):
        self.assertEqual(
            stance_hint_for_one_yt(
                upside=80,
                pattern={"name": "DB", "type": "bullish", "verdict": "confirmed"},
            ),
            "chance",
        )
        self.assertEqual(stance_hint_for_one_yt(upside=80, pattern=None), "risk")

    def test_categorize_maps_to_chips(self):
        self.assertEqual(categorize_one_yt(stance="chance"), "chance")
        self.assertEqual(categorize_one_yt(stance="lean_chance"), "lean")
        self.assertEqual(
            categorize_one_yt(stance="risk", vs_median=3.0, upside=90),
            "stretch",
        )
        self.assertEqual(
            categorize_one_yt(stance="risk", vs_median=1.2, atr_units_val=8, upside=40),
            "watch",
        )
        self.assertEqual(categorize_one_yt(stance="watch"), "watch")

    def test_build_context_sets_alert_type(self):
        ctx = build_one_yt_context(
            price=34.78,
            target=69.0,
            upside=98.7,
            portfolio_median=32.0,
            atr_pct=4.2,
            pattern={
                "name": "Double Bottom",
                "type": "bullish",
                "verdict": "confirmed",
                "confidence": 0.7,
            },
        )
        self.assertEqual(ctx["category"], "chance")
        self.assertEqual(ctx["alertType"], "one_yt_chance")


class OneYtMessageTests(unittest.TestCase):
    def test_compressed_message_shape(self):
        ctx = build_one_yt_context(
            price=34.78,
            target=69.0,
            upside=98.7,
            portfolio_median=32.0,
            atr_pct=4.2,
            pattern={
                "name": "Double Bottom",
                "type": "bullish",
                "verdict": "confirmed",
                "confidence": 0.7,
            },
        )
        msg = format_one_yt_message("IONQ", 34.78, ctx)
        self.assertIn("**98.7% below 1YT**", msg)
        self.assertIn("3.1× portfolio median (32%)", msg)
        self.assertIn("Double Bottom (confirmed)", msg)
        self.assertIn("gap ≈ 24× ATR", msg)
        self.assertIn("bullish setup + Street gap", msg)


class OneYtAlertCreateTests(unittest.TestCase):
    @patch.object(AlertsService, "_one_yt_tape_context")
    @patch.object(AlertsService, "_create_alert")
    def test_check_screener_enriches_message(self, create_alert, tape):
        create_alert.return_value = {"type": "one_yt_chance", "symbol": "IONQ"}
        tape.return_value = (
            4.2,
            {"name": "Double Bottom", "type": "bullish", "verdict": "confirmed"},
        )
        svc = AlertsService()
        svc.screener_upside_pct = 30.0
        svc.portfolio_service = MagicMock()
        svc.portfolio_service.get_screener_input.return_value = {
            "IONQ": {"currentPrice": 34.78, "analystTarget1y": 69.0},
            "AAPL": {"currentPrice": 100.0, "analystTarget1y": 110.0},
            "MSFT": {"currentPrice": 100.0, "analystTarget1y": 120.0},
        }
        created = svc._check_screener(engine=None)
        self.assertEqual(len(created), 1)
        kwargs = create_alert.call_args.kwargs
        self.assertEqual(kwargs["alert_type"], "one_yt_chance")
        self.assertIn("**", kwargs["message"])
        self.assertIn("portfolio median", kwargs["message"])
        self.assertIn("Double Bottom", kwargs["message"])
        self.assertIn("ATR", kwargs["message"])
        self.assertIn("oneYt", created[0])
        self.assertEqual(created[0]["oneYt"]["category"], "chance")

    @patch.object(AlertsService, "_one_yt_tape_context", return_value=(None, None))
    @patch.object(AlertsService, "_create_alert")
    def test_stretch_without_pattern(self, create_alert, _tape):
        create_alert.return_value = {"type": "one_yt_stretch", "symbol": "QUBT"}
        svc = AlertsService()
        svc.screener_upside_pct = 30.0
        svc.portfolio_service = MagicMock()
        svc.portfolio_service.get_screener_input.return_value = {
            "QUBT": {"currentPrice": 10.0, "analystTarget1y": 25.0},  # 150%
            "AAPL": {"currentPrice": 100.0, "analystTarget1y": 110.0},  # 10%
            "MSFT": {"currentPrice": 100.0, "analystTarget1y": 120.0},  # 20%
        }
        created = svc._check_screener(engine=None)
        self.assertEqual(len(created), 1)
        self.assertEqual(create_alert.call_args.kwargs["alert_type"], "one_yt_stretch")
        self.assertEqual(created[0]["oneYt"]["category"], "stretch")

    @patch.object(AlertsService, "_one_yt_tape_context", return_value=(None, None))
    @patch.object(AlertsService, "_create_alert")
    def test_below_threshold_skipped(self, create_alert, _tape):
        svc = AlertsService()
        svc.screener_upside_pct = 30.0
        svc.portfolio_service = MagicMock()
        svc.portfolio_service.get_screener_input.return_value = {
            "AAPL": {"currentPrice": 100.0, "analystTarget1y": 120.0},  # 20%
        }
        created = svc._check_screener(engine=None)
        self.assertEqual(created, [])
        create_alert.assert_not_called()


class SaiOneYtFactorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.llm = MagicMock()
        self.llm.aggregate_note_syntheses.return_value = {
            "summary": "",
            "sentiment": "neutral",
            "growthTrajectory": [],
            "revenueProjections": [],
            "catalystsToWatch": [],
            "provider": "rules",
        }
        self.llm.hard_trigger.return_value = None
        self.overlay = AssessmentOverlayService(self.llm)

    def test_one_yt_factor_uses_enriched_message(self) -> None:
        base = {
            "action": "hold",
            "confidence": "medium",
            "rationale": "Neutral.",
            "factors": [],
            "provider": "rules",
            "asOfDate": "2026-07-18",
            "actionSource": "rules_fallback",
        }
        personal = {
            "symbol": "IONQ",
            "currentPrice": 34.78,
            "noteSyntheses": [],
            "unsynthesizedNoteCount": 0,
            "alerts": [
                {
                    "type": "one_yt_chance",
                    "price": 34.78,
                    "referenceValue": 69.0,
                    "message": (
                        "IONQ at $34.78 is **98.7% below 1YT** ($69.00) · "
                        "3.1× portfolio median (32%) — Double Bottom (confirmed); "
                        "gap ≈ 24× ATR (4.2%) — bullish setup + Street gap."
                    ),
                }
            ],
            "screening": {},
        }
        result = self.overlay.apply(base, personal)
        self.assertEqual(result["action"], "watch")
        joined = " ".join(result["factors"])
        self.assertIn("portfolio median", joined)
        self.assertIn("Double Bottom", joined)
        self.assertNotIn("substantial upside to your target", joined)


if __name__ == "__main__":
    unittest.main()
