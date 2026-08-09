"""Tests for portfolio Intent inference, Fit nudge, and attention flag."""

import unittest

from services.portfolio_intent import (
    attention_for_actions,
    fit_intent_nudge,
    harvest_intent_lean,
    infer_intent,
    resolve_intent,
)
from services.proposal_service import ProposalService


class PortfolioIntentTests(unittest.TestCase):
    def test_infer_user_examples(self) -> None:
        # X: watch, buy=sell → tactical
        self.assertEqual(infer_intent(held=0, buy_qty=100, sell_qty=100), "tactical")
        # Y: watch, buy≫sell → accumulate
        self.assertEqual(infer_intent(held=0, buy_qty=100, sell_qty=10), "accumulate")
        # Z: large hold, buy≈sell small → core
        self.assertEqual(infer_intent(held=1000, buy_qty=100, sell_qty=100), "core")
        # A: large hold, buy≫sell → core_accumulate
        self.assertEqual(
            infer_intent(held=1000, buy_qty=100, sell_qty=10), "core_accumulate"
        )
        # Divest: held, no buy, sell ≥25% of held
        self.assertEqual(infer_intent(held=1000, buy_qty=0, sell_qty=300), "divest")
        self.assertEqual(infer_intent(held=100, buy_qty=0, sell_qty=100), "divest")
        # Light trim only (<25%) stays core_accumulate
        self.assertEqual(infer_intent(held=1000, buy_qty=0, sell_qty=100), "core_accumulate")

    def test_override_wins(self) -> None:
        resolved = resolve_intent(
            held=0, buy_qty=100, sell_qty=100, override="core_accumulate"
        )
        self.assertEqual(resolved["inferred"], "tactical")
        self.assertEqual(resolved["code"], "core_accumulate")
        self.assertEqual(resolved["source"], "override")

    def test_attention_opposite_is_warn(self) -> None:
        att = attention_for_actions(band_action="buy", sai_action="sell")
        self.assertTrue(att["flag"])
        self.assertEqual(att["level"], "warn")
        soft = attention_for_actions(band_action="buy", sai_action="watch")
        self.assertTrue(soft["flag"])
        self.assertEqual(soft["level"], "info")
        same = attention_for_actions(band_action="watch", sai_action="hold")
        self.assertFalse(same["flag"])

    def test_fit_and_harvest_leans(self) -> None:
        delta, factors = fit_intent_nudge(
            intent_code="tactical", action="sell", held=0, sell_qty=100
        )
        self.assertEqual(delta, 2.0)
        self.assertTrue(factors)
        lean, note = harvest_intent_lean(intent_code="tactical", is_trim=True)
        self.assertEqual(lean, 4.0)
        self.assertIsNotNone(note)
        core_lean, _ = harvest_intent_lean(
            intent_code="core_accumulate", is_trim=False, held=1000, sell_qty=500
        )
        self.assertEqual(core_lean, -2.0)

    def test_proposal_emits_intent_and_attention(self) -> None:
        proposal = ProposalService().build(
            symbol="TTD",
            action="buy",
            confidence="high",
            context={
                "currentPrice": 50,
                "screening": {
                    "score": 5,
                    "upsidePct": -10,
                    "tradeBelowPrice": 40,
                    "tradeBelowShares": 100,
                    "tradeAbovePrice": 60,
                    "tradeAboveShares": -100,
                },
                "holding": None,
                "alerts": [],
            },
            previous_actions=[],
        )
        self.assertEqual(proposal["intent"]["code"], "tactical")
        self.assertIn("attention", proposal)
        # Low score → sell/watch band vs SAI buy → attention
        if proposal["action"] != "buy":
            self.assertTrue(proposal["attention"]["flag"])
        self.assertEqual(proposal["fitExtensions"]["holdingPeriodBias"], "tactical")


if __name__ == "__main__":
    unittest.main()
