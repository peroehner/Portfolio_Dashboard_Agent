"""Unit tests for the trading proposal scaffold (Slices 1–3)."""

import os
import unittest
from unittest.mock import patch

from services.proposal_service import (
    FIT_EXTENSION_KEYS,
    ProposalService,
    action_for_band_code,
    base_confidence_for_total,
    pillar_scales_from_track_record,
    score_band_for_total,
)


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
        self.assertEqual(proposal["authority"], "proposal_band")
        self.assertIn(proposal["action"], ("buy", "watch", "sell"))
        self.assertIn(proposal["confidence"], ("high", "medium", "low"))
        self.assertEqual(proposal.get("confidenceSource"), "proposal_band")
        self.assertEqual(proposal["legacySai"]["action"], "watch")
        self.assertEqual(proposal["legacySai"]["confidence"], "medium")
        self.assertIn("diverged", proposal["legacySai"])
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
        self.assertGreaterEqual(proposal["stability"]["sameActionStreak"], 1)
        self.assertIn("confirmed", proposal["stability"])

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

    def test_fit_prefs_dividend_and_volatility(self) -> None:
        proposal = self.svc.build(
            symbol="DIV",
            action="watch",
            confidence="medium",
            context={
                "currentPrice": 40,
                "screening": {"score": 10, "upsidePct": 10, "flags": []},
                "fundamentals": {"beta": 0.8, "dividendYield": 0.03},
                "holding": None,
                "alerts": [],
            },
            fit_prefs={
                "targetAnnualDividend": 8000,
                "volatilityPreference": "low",
                "maxSingleNameWeightPct": 12,
            },
            portfolio_annual_dividend=1000,
            previous_actions=[],
        )
        self.assertEqual(proposal["fitExtensions"]["targetAnnualDividend"], 8000.0)
        self.assertEqual(proposal["fitExtensions"]["volatilityPreference"], "low")
        self.assertEqual(proposal["fitExtensions"]["maxSingleNameWeightPct"], 12.0)
        factors = " ".join(proposal["components"]["portfolioFit"]["factors"]).lower()
        self.assertIn("income gap", factors)
        self.assertIn("beta", factors)

    def test_stability_gate_holds_prior_action(self) -> None:
        with patch.dict(os.environ, {"PROPOSAL_STABILITY_GATE": "1"}):
            import importlib

            import services.proposal_service as mod

            importlib.reload(mod)
            svc = mod.ProposalService()
            proposal = svc.build(
                symbol="FLIP",
                action="buy",
                confidence="high",
                context={"screening": {}, "alerts": [], "holding": None},
                previous_actions=["hold"],
            )
            self.assertEqual(proposal["action"], "hold")
            self.assertTrue(proposal["stability"]["gated"])
            self.assertNotEqual(proposal["stability"]["rawAction"], proposal["action"])
            importlib.reload(mod)

    def test_valuation_stretch_and_band_bias(self) -> None:
        proposal = self.svc.build(
            symbol="AAPL",
            action="hold",
            confidence="medium",
            context={
                "currentPrice": 200,
                "analystTarget1y": 180,
                "screening": {"score": 10, "upsidePct": -10, "flags": []},
                "fundamentals": {
                    "valuation": {"trailingPe": 41.0, "pegRatio": 2.7},
                    "growthProfitability": {"operatingMargins": 0.3, "revenueGrowth": 0.15},
                },
                "holding": {"quantity": 10, "weightPct": 12.0},
                "alerts": [],
            },
            previous_actions=["hold"],
        )
        factors = " ".join(proposal["components"]["state"]["factors"]).lower()
        self.assertTrue("peg" in factors or "p/e" in factors or "above target" in factors)
        self.assertIn("bandBias", proposal)
        self.assertFalse(proposal["bandBias"]["advisory"])
        mapped = action_for_band_code(proposal["bandBias"]["code"])
        if proposal["stability"].get("gated"):
            self.assertEqual(proposal["action"], "hold")
            self.assertEqual(proposal["stability"]["rawAction"], mapped)
        else:
            self.assertEqual(proposal["action"], mapped)
        self.assertEqual(proposal["authority"], "proposal_band")

    def test_track_record_scales(self) -> None:
        scales = pillar_scales_from_track_record(
            {
                "byKind": {
                    "recommendation": {"wins": 10, "losses": 2, "hitRate": 10 / 12},
                    "pattern": {"wins": 8, "losses": 2, "hitRate": 0.8},
                    "confluence": {"wins": 7, "losses": 3, "hitRate": 0.7},
                }
            }
        )
        self.assertGreater(scales["state"], 1.0)
        self.assertGreater(scales["trigger"], 1.0)
        thin = pillar_scales_from_track_record(
            {"byKind": {"recommendation": {"wins": 1, "losses": 0, "hitRate": 1.0}}}
        )
        self.assertEqual(thin["state"], 1.0)

    def test_score_band_cuts_match_conf_and_fit_band(self) -> None:
        """Shared ≥75 / ≥35 / else cuts; Fit Band = raw, Conf base uses same helper."""
        self.assertEqual(score_band_for_total(75), "high")
        self.assertEqual(score_band_for_total(74), "medium")
        self.assertEqual(score_band_for_total(35), "medium")
        self.assertEqual(score_band_for_total(34), "low")
        self.assertEqual(score_band_for_total(None), "unknown")
        self.assertEqual(base_confidence_for_total(total=40), "medium")
        self.assertEqual(base_confidence_for_total(total=34), "low")


if __name__ == "__main__":
    unittest.main()
