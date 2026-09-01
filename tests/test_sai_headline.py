"""SAI headline copy after Pass 2."""

import unittest

from services.inspector_service import InspectorService
from services.llm_client import LLMClient


class SaiHeadlineTests(unittest.TestCase):
    def test_watch_points_at_what_to_watch_when_items_exist(self):
        headline = InspectorService._headline_for_action(
            "watch",
            "bearish",
            ["ARR growth", "Operating margin"],
        )
        self.assertIn("What to watch", headline)
        self.assertIn("bearish notes flagged", headline)
        self.assertNotIn("catalysts approaching", headline)

    def test_watch_without_items_keeps_approaching(self):
        headline = InspectorService._headline_for_action("watch", "neutral", [])
        self.assertEqual(headline, "Monitor — catalysts approaching")

    def test_sell_with_holding_suggests_taking_profits(self):
        headline = InspectorService._headline_for_action(
            "sell", "neutral", [], has_holding=True
        )
        self.assertEqual(headline, "Consider taking profits or reducing")

    def test_sell_without_holding_avoids_initiating(self):
        headline = InspectorService._headline_for_action(
            "sell", "neutral", [], has_holding=False
        )
        self.assertEqual(headline, "Avoid initiating a position")
        self.assertNotIn("taking profits", headline)

    def test_hold_without_holding_stays_sidelines(self):
        headline = InspectorService._headline_for_action(
            "hold", "neutral", [], has_holding=False
        )
        self.assertEqual(headline, "Stay on the sidelines")

    def test_has_open_position_from_quantity(self):
        self.assertTrue(InspectorService._has_open_position({"quantity": 10}))
        self.assertFalse(InspectorService._has_open_position({"quantity": 0}))
        self.assertFalse(InspectorService._has_open_position(None))


class OverlayPromptTests(unittest.TestCase):
    def test_overlay_prompt_stays_on_symbol_and_asks_for_metric_wrap(self):
        client = LLMClient()
        prompt = client._overlay_system_prompt("CRWD")
        self.assertIn("ONLY about CRWD", prompt)
        self.assertIn("Do not name other tickers", prompt)
        self.assertIn("nearby words that state its meaning", prompt)
        self.assertIn("**180x forward P/E**", prompt)
        self.assertIn("**1.1% of portfolio**", prompt)


if __name__ == "__main__":
    unittest.main()
