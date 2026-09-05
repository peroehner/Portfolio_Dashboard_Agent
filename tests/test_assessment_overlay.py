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

    def _enable_overlay_llm(self) -> None:
        self.llm.active_provider.return_value = "gemini"
        self.llm._classify_llm_error.return_value = "LLM unavailable — used rules engine."

    def test_overlay_llm_locks_buy_sell_but_allows_hold_to_watch(self) -> None:
        self._enable_overlay_llm()
        self.llm.generate_overlay_assessment.return_value = {
            "action": "buy",
            "confidence": "high",
            "rationale": "Book overlay tried to upgrade.",
            "factors": ["Weight 4% — room to add."],
            "watchItems": ["Watch sell-above at 200."],
            "provider": "gemini",
        }
        base = {
            "action": "hold",
            "confidence": "medium",
            "rationale": "Market hold.",
            "factors": ["Neutral tape."],
            "provider": "gemini",
            "asOfDate": "2026-08-17",
            "actionSource": "llm",
        }
        personal = {
            "symbol": "AAPL",
            "currentPrice": 180,
            "noteSyntheses": [],
            "unsynthesizedNoteCount": 0,
            "alerts": [],
            "screening": {},
        }
        result = self.overlay.apply(base, personal)
        self.assertEqual(result["action"], "hold")
        self.assertEqual(result["confidence"], "medium")
        self.assertEqual(result["actionSource"], "base_assessment+overlay_llm")
        self.assertIn("Watch sell-above at 200.", result["watchItems"])

        self.llm.generate_overlay_assessment.return_value["action"] = "watch"
        self.llm.generate_overlay_assessment.return_value["confidence"] = "low"
        watched = self.overlay.apply(base, personal)
        self.assertEqual(watched["action"], "watch")
        self.assertEqual(watched["confidence"], "low")

    def test_overlay_llm_hard_trigger_still_owns_action(self) -> None:
        self._enable_overlay_llm()
        self.llm.hard_trigger.return_value = {
            "action": "sell",
            "confidence": "high",
            "reason": "price is at or above your sell-above threshold (200)",
        }
        self.llm.generate_overlay_assessment.return_value = {
            "action": "hold",
            "confidence": "low",
            "rationale": "Tried to ignore the threshold.",
            "factors": ["Ignore me."],
            "watchItems": ["Threshold already fired."],
            "provider": "gemini",
        }
        base = {
            "action": "hold",
            "confidence": "medium",
            "rationale": "Market hold.",
            "factors": [],
            "provider": "gemini",
            "asOfDate": "2026-08-17",
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

    def test_overlay_llm_error_falls_back_to_rules(self) -> None:
        self._enable_overlay_llm()
        self.llm.generate_overlay_assessment.side_effect = RuntimeError("429 quota")
        base = {
            "action": "hold",
            "confidence": "medium",
            "rationale": "Market hold.",
            "factors": [],
            "provider": "gemini",
            "asOfDate": "2026-08-17",
            "actionSource": "llm",
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
        self.assertTrue(result.get("llmFallback"))
        self.assertTrue(any("personal target" in f.lower() for f in result["factors"]))

    def test_overlay_packet_is_slim(self) -> None:
        base = {
            "action": "hold",
            "confidence": "medium",
            "rationale": "Market hold.",
            "factors": ["Tape mixed."],
            "asOfDate": "2026-08-17",
        }
        personal = {
            "symbol": "NVDA",
            "companyName": "NVIDIA Corporation",
            "currentPrice": 100,
            "buyBelow": 90,
            "sellAbove": 130,
            "targetPrice": 140,
            "fitPrefs": {"targetAnnualDividend": 12000, "maxSingleNameWeightPct": 20},
            "portfolioAnnualDividend": 8000,
            "holding": {"quantity": 10, "weightPct": 8.5, "gainPct": 12, "annualDividend": 0.4},
            "alerts": [{"type": "winner_trim_candidate", "message": "Trim candidate"}],
            "screening": {"upsidePct": 22, "fibDistancePct": 1.2},
            "fundamentals": {"valuation": {}, "technical": {"shouldNot": "leak"}},
            "noteSynthesis": {
                "summary": "Notes",
                "sentiment": "bullish",
                "growthTrajectory": [],
                "catalystsToWatch": [],
            },
        }
        packet = self.overlay.build_overlay_packet(base, personal, personal["noteSynthesis"], None)
        blob = str(packet)
        self.assertNotIn("shouldNot", blob)
        self.assertNotIn("scores", packet)
        self.assertNotIn("technical", packet.get("personal") or {})
        self.assertEqual(packet["constraints"]["lockedAction"], "hold")
        self.assertEqual(packet["companyName"], "NVIDIA Corporation")
        self.assertEqual(packet["personal"]["alerts"][0]["type"], "winner_trim_candidate")
        self.assertEqual(packet["personal"]["dividend"]["gapVsTarget"], 4000)

    def test_intent_and_fit_prefs_nudge_hold_to_watch(self) -> None:
        base = {
            "action": "hold",
            "confidence": "medium",
            "rationale": "Neutral market view.",
            "factors": ["Tape mixed."],
            "provider": "rules",
            "asOfDate": "2026-09-05",
        }
        personal = {
            "symbol": "AAPL",
            "currentPrice": 180,
            "targetPrice": 200,
            "intentOverride": "accumulate",
            "fitPrefs": {
                "targetAnnualDividend": 10000,
                "volatilityPreference": "low",
                "maxSingleNameWeightPct": 10,
            },
            "portfolioAnnualDividend": 2000,
            "fundamentals": {"beta": 1.6},
            "holding": {
                "quantity": 100,
                "weightPct": 15.0,
                "annualDividend": 0.96,
            },
            "screening": {
                "tradeBelowPrice": 160,
                "tradeBelowShares": 50,
                "tradeAbovePrice": 220,
                "tradeAboveShares": 10,
            },
            "noteSyntheses": [],
            "unsynthesizedNoteCount": 0,
            "alerts": [],
        }
        result = self.overlay.apply(base, personal)
        self.assertEqual(result["action"], "watch")
        joined = " ".join(result["factors"])
        self.assertIn("Intent", joined)
        self.assertTrue(
            ("Income" in joined) or ("Concentration" in joined) or ("Volatility" in joined),
            joined,
        )


if __name__ == "__main__":
    unittest.main()
