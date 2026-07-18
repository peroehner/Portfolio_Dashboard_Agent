"""Unit tests for Fib role metadata, alert wording, and Confluence / SAI wiring."""
import unittest
from unittest.mock import MagicMock, patch

from services.alerts_service import AlertsService
from services.assessment_overlay_service import AssessmentOverlayService
from services.confluence_service import compute_confluence
from services.fib_roles import (
    build_fib_context,
    describe_fib_label,
    format_fib_proximity_message,
    ratio_from_label,
)


class FibRoleMetaTests(unittest.TestCase):
    def test_ratio_from_percent_and_decimal(self):
        self.assertEqual(ratio_from_label("61.8%"), 0.618)
        self.assertEqual(ratio_from_label("0.618"), 0.618)
        self.assertEqual(ratio_from_label("50%"), 0.5)

    def test_golden_pocket_metadata(self):
        meta = describe_fib_label("61.8%")
        self.assertIsNotNone(meta)
        self.assertEqual(meta["role"], "golden")
        self.assertEqual(meta["roleName"], "Golden Pocket")
        self.assertIn("up-move", meta["cue"])

    def test_proximity_message_names_role_and_side(self):
        level = {"label": "61.8%", "ratio": 0.618, "price": 393.94}
        ctx = build_fib_context(level=level, price=393.82, distance_pct=0.03)
        msg = format_fib_proximity_message("MSFT", 393.82, ctx)
        self.assertEqual(
            msg,
            "MSFT at $393.82 is just below **61.8% Golden Pocket** at $393.94 (0.03%) "
            "— holding keeps larger up-move intact; break opens path toward Base.",
        )


class FibAlertCreateTests(unittest.TestCase):
    @patch.object(AlertsService, "_create_alert")
    def test_check_fib_proximity_uses_enriched_message(self, create_alert):
        create_alert.return_value = {"type": "fib_proximity"}
        svc = AlertsService()
        svc.fib_proximity_pct = 1.0
        svc.fib_service = MagicMock()
        svc.fib_service.nearest_level.return_value = {
            "level": {
                "label": "61.8%",
                "ratio": 0.618,
                "price": 100.0,
                "role": "golden",
                "roleName": "Golden Pocket",
                "cue": "holding keeps larger up-move intact; break opens path toward Base",
            },
            "distancePct": 0.4,
        }
        created = svc._check_fib_proximity({"symbol": "MSFT", "currentPrice": 99.6})
        self.assertEqual(len(created), 1)
        kwargs = create_alert.call_args.kwargs
        self.assertEqual(kwargs["alert_type"], "fib_proximity")
        self.assertIn("**61.8% Golden Pocket**", kwargs["message"])
        self.assertIn("just below", kwargs["message"])
        self.assertIn("(0.40%)", kwargs["message"])

    @patch.object(AlertsService, "_has_pattern_key_level_near", return_value=False)
    @patch.object(AlertsService, "_create_alert")
    def test_lonely_shallow_is_suppressed(self, create_alert, _pattern):
        svc = AlertsService()
        svc.fib_proximity_pct = 1.0
        svc.fib_service = MagicMock()
        svc.fib_service.nearest_level.return_value = {
            "level": {
                "label": "23.6%",
                "ratio": 0.236,
                "price": 100.0,
                "role": "shallow",
                "roleName": "Shallow",
            },
            "distancePct": 0.3,
        }
        created = svc._check_fib_proximity(
            {"symbol": "MGNI", "currentPrice": 99.7},
            true_signatures=set(),
        )
        self.assertEqual(created, [])
        create_alert.assert_not_called()

    @patch.object(AlertsService, "_has_pattern_key_level_near", return_value=False)
    @patch.object(AlertsService, "_create_alert")
    def test_shallow_emits_with_trade_co_trigger(self, create_alert, _pattern):
        create_alert.return_value = {"type": "fib_proximity"}
        svc = AlertsService()
        svc.fib_proximity_pct = 1.0
        svc.fib_service = MagicMock()
        svc.fib_service.nearest_level.return_value = {
            "level": {
                "label": "23.6%",
                "ratio": 0.236,
                "price": 100.0,
                "role": "shallow",
                "roleName": "Shallow",
            },
            "distancePct": 0.3,
        }
        sigs = {AlertsService._signature("MGNI", "trade_below_near", 95.0, None)}
        created = svc._check_fib_proximity(
            {"symbol": "MGNI", "currentPrice": 99.7},
            true_signatures=sigs,
        )
        self.assertEqual(len(created), 1)
        create_alert.assert_called_once()


class SaiFibFactorTests(unittest.TestCase):
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

    def test_fib_alert_factor_quotes_role(self) -> None:
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
            "symbol": "MSFT",
            "currentPrice": 393.82,
            "noteSyntheses": [],
            "unsynthesizedNoteCount": 0,
            "alerts": [
                {
                    "type": "fib_proximity",
                    "fibLevel": "61.8%",
                    "price": 393.82,
                    "referenceValue": 393.94,
                }
            ],
            "screening": {},
        }
        result = self.overlay.apply(base, personal)
        self.assertEqual(result["action"], "watch")
        joined = " ".join(result["factors"])
        self.assertIn("Golden Pocket", joined)
        self.assertNotIn("near a key Fibonacci level", joined)


class ConfluenceFibVoteTests(unittest.TestCase):
    def test_golden_hold_votes_bullish(self):
        conf = compute_confluence(
            {
                "price": 100.2,
                "swing": {
                    "structure": "range / mixed",
                    "nearestLevel": {
                        "label": "61.8%",
                        "ratio": 0.618,
                        "price": 100.0,
                        "role": "golden",
                        "roleName": "Golden Pocket",
                        "distancePct": 0.2,
                    },
                },
            }
        )
        self.assertIsNotNone(conf)
        fib_votes = [v for v in conf["votes"] if v["agent"] == "fib"]
        self.assertEqual(len(fib_votes), 1)
        self.assertEqual(fib_votes[0]["direction"], "bull")
        self.assertIn("Golden", fib_votes[0]["label"])

    def test_center_below_votes_bearish(self):
        conf = compute_confluence(
            {
                "price": 99.5,
                "swing": {
                    "nearestLevel": {
                        "label": "50.0%",
                        "ratio": 0.5,
                        "price": 100.0,
                        "role": "center",
                        "roleName": "Center Line",
                        "distancePct": 0.5,
                    },
                },
            }
        )
        fib_votes = [v for v in conf["votes"] if v["agent"] == "fib"]
        self.assertEqual(len(fib_votes), 1)
        self.assertEqual(fib_votes[0]["direction"], "bear")

    def test_far_fib_does_not_vote(self):
        conf = compute_confluence(
            {
                "price": 110.0,
                "trend": {"maStack": "bullish", "slopePctPerYr": 20.0},
                "swing": {
                    "nearestLevel": {
                        "label": "61.8%",
                        "ratio": 0.618,
                        "price": 100.0,
                        "role": "golden",
                        "roleName": "Golden Pocket",
                        "distancePct": 9.0,
                    },
                },
            }
        )
        self.assertIsNotNone(conf)
        agents = {v["agent"] for v in conf["votes"]}
        self.assertNotIn("fib", agents)

    def test_shallow_weighs_less_than_golden(self):
        common = {
            "price": 100.1,
            "trend": {"maStack": "mixed", "slopePctPerYr": 0.0},
        }
        golden = compute_confluence(
            {
                **common,
                "swing": {
                    "nearestLevel": {
                        "label": "61.8%",
                        "ratio": 0.618,
                        "price": 100.0,
                        "role": "golden",
                        "roleName": "Golden Pocket",
                        "distancePct": 0.1,
                    },
                },
            }
        )
        shallow = compute_confluence(
            {
                **common,
                "swing": {
                    "nearestLevel": {
                        "label": "23.6%",
                        "ratio": 0.236,
                        "price": 100.0,
                        "role": "shallow",
                        "roleName": "Shallow",
                        "distancePct": 0.1,
                    },
                },
            }
        )

        def fib_w(conf):
            for v in conf["votes"]:
                if v["agent"] == "fib":
                    return v["weight"]
            return 0.0

        self.assertGreater(fib_w(golden), fib_w(shallow))

    def test_shallow_skipped_in_strong_trend(self):
        conf = compute_confluence(
            {
                "price": 100.1,
                "trend": {"maStack": "bullish", "slopePctPerYr": 18.0},
                "swing": {
                    "nearestLevel": {
                        "label": "23.6%",
                        "ratio": 0.236,
                        "price": 100.0,
                        "role": "shallow",
                        "roleName": "Shallow",
                        "distancePct": 0.1,
                    },
                },
            }
        )
        agents = {v["agent"] for v in conf["votes"]}
        self.assertNotIn("fib", agents)

    def test_shallow_kept_when_trend_mixed(self):
        conf = compute_confluence(
            {
                "price": 100.1,
                "trend": {"maStack": "mixed", "slopePctPerYr": 0.0},
                "swing": {
                    "nearestLevel": {
                        "label": "23.6%",
                        "ratio": 0.236,
                        "price": 100.0,
                        "role": "shallow",
                        "roleName": "Shallow",
                        "distancePct": 0.1,
                    },
                },
            }
        )
        agents = {v["agent"] for v in conf["votes"]}
        self.assertIn("fib", agents)


if __name__ == "__main__":
    unittest.main()
