import unittest
from unittest.mock import MagicMock

from services.assessment_overlay_service import AssessmentOverlayService


class AssessmentOverlayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.llm = MagicMock()
        self.llm.aggregate_note_syntheses.return_value = {
            "summary": "Revenue grew 30%",
            "sentiment": "bullish",
            "growthTrajectory": [],
            "revenueProjections": [],
            "catalystsToWatch": [],
            "provider": "rules",
        }
        self.llm.hard_trigger.return_value = None
        self.overlay = AssessmentOverlayService(self.llm)

    def test_hard_trigger_overrides_base(self) -> None:
        self.llm.hard_trigger.return_value = {
            "action": "sell",
            "confidence": "high",
            "reason": "price is at or above your sell-above threshold (200)",
        }
        base = {
            "action": "hold",
            "confidence": "medium",
            "rationale": "Neutral market view.",
            "factors": ["Analyst upside moderate."],
            "provider": "gemini",
            "asOfDate": "2026-07-06",
            "actionSource": "llm",
        }
        personal = {
            "symbol": "AAPL",
            "currentPrice": 205,
            "sellAbove": 200,
            "noteSyntheses": [],
            "unsynthesizedNoteCount": 0,
            "alerts": [],
            "screening": {},
        }
        result = self.overlay.apply(base, personal)
        self.assertEqual(result["action"], "sell")
        self.assertEqual(result["confidence"], "high")
        self.assertEqual(result["actionSource"], "rule_hard_trigger")

    def test_personal_target_promotes_watch(self) -> None:
        base = {
            "action": "hold",
            "confidence": "medium",
            "rationale": "Market neutral.",
            "factors": ["No major trigger."],
            "provider": "rules",
            "asOfDate": "2026-07-06",
            "actionSource": "rules_fallback",
        }
        personal = {
            "symbol": "MSFT",
            "currentPrice": 100,
            "targetPrice": 150,
            "noteSyntheses": [],
            "unsynthesizedNoteCount": 0,
            "alerts": [],
            "screening": {},
        }
        result = self.overlay.apply(base, personal)
        self.assertEqual(result["action"], "watch")
        self.assertTrue(any("personal target" in f.lower() for f in result["factors"]))


if __name__ == "__main__":
    unittest.main()
