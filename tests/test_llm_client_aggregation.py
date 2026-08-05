"""Unit tests for note synthesis aggregation de-duplication."""

import unittest

from services.llm_client import LLMClient


class LlmClientAggregationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = LLMClient()

    def test_low_signal_summaries_collapse_to_single_line(self) -> None:
        syntheses = [
            {
                "summary": "No actionable financial or growth insights could be extracted from the provided note.",
                "growthTrajectory": [],
                "revenueProjections": [],
                "catalystsToWatch": [],
                "sentiment": "neutral",
                "provider": "openai",
            },
            {
                "summary": "The provided note contains no discernible information for analysis.",
                "growthTrajectory": [],
                "revenueProjections": [],
                "catalystsToWatch": [],
                "sentiment": "neutral",
                "provider": "openai",
            },
            {
                "summary": "The provided note contains no discernible financial information or growth thesis for Apple.",
                "growthTrajectory": [],
                "revenueProjections": [],
                "catalystsToWatch": [],
                "sentiment": "neutral",
                "provider": "openai",
            },
        ]

        out = self.client.aggregate_note_syntheses("AAPL", syntheses)
        self.assertEqual(
            out["summary"], "Notes reviewed; no specific financial thesis extracted yet."
        )

    def test_informative_summary_dedupes_near_duplicates(self) -> None:
        syntheses = [
            {"summary": "Services revenue grew 18% YoY.", "sentiment": "bullish"},
            {"summary": "Services revenue grew 18% yoy", "sentiment": "bullish"},
            {"summary": "Hardware margin improved 200 bps.", "sentiment": "bullish"},
        ]

        out = self.client.aggregate_note_syntheses("AAPL", syntheses)
        self.assertEqual(
            out["summary"], "Services revenue grew 18% YoY. | Hardware margin improved 200 bps."
        )


if __name__ == "__main__":
    unittest.main()
