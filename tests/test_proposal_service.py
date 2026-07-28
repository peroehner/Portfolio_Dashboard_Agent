"""Unit tests for the trading proposal scaffold (Slice 1)."""

import unittest

from services.proposal_service import FIT_EXTENSION_KEYS, ProposalService


class ProposalServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.svc = ProposalService()

    def test_schema_and_score_bounds(self) -> None:
        proposal = self.svc.build(
            symbol="aapl",
            action="watch",
            confidence="medium",
            rationale="Scaffold test",
            factors=["Your notes: growth ok"],
            action_source="base_assessment+overlay",
            context={
                "currentPrice": 100,
                "targetPrice": 140,
                "analystTarget1y": 145,
                "buyBelow": 95,
                "sellAbove": 160,
                "screening": {"score": 40, "upsidePct": 45, "flags": ["high_upside"]},
                "fundamentals": {"operatingMargins": 0.2, "revenueGrowth": 0.12},
                "holding": {"quantity": 10, "weightPct": 8.5, "gainPct": 12, "annualDividend": 0.96},
                "alerts": [{"type": "fib_proximity", "message": "Near Fib"}],
            },
            previous_actions=["watch", "hold"],
        )
        self.assertEqual(proposal["schemaVersion"], 1)
        self.assertEqual(proposal["symbol"], "AAPL")
        self.assertEqual(proposal["authority"], "assessment")
        self.assertEqual(proposal["action"], "watch")
        scores = proposal["scores"]
        self.assertGreaterEqual(scores["state"], 0)
        self.assertLessEqual(scores["state"], 50)
        self.assertGreaterEqual(scores["trigger"], 0)
        self.assertLessEqual(scores["trigger"], 30)
        self.assertGreaterEqual(scores["portfolioFit"], 0)
        self.assertLessEqual(scores["portfolioFit"], 20)
        self.assertEqual(
            scores["total"],
            scores["state"] + scores["trigger"] + scores["portfolioFit"],
        )
        for key in FIT_EXTENSION_KEYS:
            self.assertIn(key, proposal["fitExtensions"])
            self.assertIsNone(proposal["fitExtensions"][key])
        self.assertEqual(proposal["stability"]["sameActionStreak"], 2)
        self.assertTrue(proposal["stability"]["confirmed"])

    def test_hard_trigger_and_concentration_veto(self) -> None:
        proposal = self.svc.build(
            symbol="CONC",
            action="buy",
            confidence="high",
            action_source="rule_hard_trigger",
            context={
                "currentPrice": 50,
                "sellAbove": 40,
                "holding": {"quantity": 100, "weightPct": 45.0, "gainPct": 80},
                "screening": {"score": 20, "flags": ["above_sell"]},
                "alerts": [],
            },
            previous_actions=["hold"],
        )
        codes = {v["code"] for v in proposal["vetoes"]}
        self.assertIn("hard_threshold", codes)
        self.assertIn("concentration", codes)
        self.assertIn("sell_threshold_blocks_buy", codes)
        self.assertIsNotNone(proposal["stability"]["hysteresisHint"])
        self.assertEqual(proposal["stability"]["sameActionStreak"], 1)
        self.assertFalse(proposal["stability"]["confirmed"])

    def test_build_from_assessment_uses_context(self) -> None:
        assessment = {
            "symbol": "MSFT",
            "action": "hold",
            "confidence": "low",
            "rationale": "Neutral",
            "factors": [],
            "actionSource": "rules_fallback",
        }
        proposal = self.svc.build_from_assessment(
            assessment,
            context={
                "symbol": "MSFT",
                "currentPrice": 400,
                "screening": {"score": 5, "upsidePct": 5, "flags": []},
                "holding": None,
                "alerts": [],
            },
            previous_actions=[],
        )
        self.assertEqual(proposal["action"], "hold")
        self.assertEqual(proposal["scores"]["portfolioFit"], 8)  # watchlist neutral base


if __name__ == "__main__":
    unittest.main()
