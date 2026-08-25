"""Unit tests for named ticker segments + include/exclude matching."""

from __future__ import annotations

import unittest

from services.ticker_segments import (
    expand_filter,
    export_segments_text,
    merge_segments,
    normalize_segment_name,
    parse_command,
    symbol_matches_filter,
)


class TickerSegmentsTests(unittest.TestCase):
    def test_normalize_name(self):
        self.assertEqual(normalize_segment_name("ai"), "AI")
        self.assertEqual(normalize_segment_name("Semi_AI"), "SEMI_AI")
        self.assertIsNone(normalize_segment_name("1bad"))
        self.assertIsNone(normalize_segment_name("@AI"))

    def test_parse_commands(self):
        self.assertEqual(
            parse_command("@AI=tsm, mr, -intc"),
            {"op": "define", "name": "AI", "match": "tsm, mr, -intc"},
        )
        self.assertEqual(parse_command("@AI!"), {"op": "delete", "name": "AI"})
        self.assertIsNone(parse_command("mu, doc"))
        self.assertIsNone(parse_command("@AI"))

    def test_expand_and_exclude(self):
        segs = {"AI": "tsm, mr, nbis, -intc"}
        self.assertTrue(symbol_matches_filter("MRVL", "@AI", segments=segs))
        self.assertTrue(symbol_matches_filter("TSM", "@AI", segments=segs))
        self.assertFalse(symbol_matches_filter("INTC", "@AI", segments=segs))
        self.assertFalse(symbol_matches_filter("INTC", "in, -intc", segments=segs))
        self.assertTrue(symbol_matches_filter("MU", "mu, -mubi", segments=segs))
        self.assertFalse(symbol_matches_filter("MUBI", "mu, -mubi", segments=segs))

    def test_incomplete_at_does_not_filter(self):
        segs = {"AI": "tsm, mr"}
        # Bare @ while typing should not wipe the list.
        self.assertTrue(symbol_matches_filter("AAPL", "@", segments=segs))
        self.assertTrue(symbol_matches_filter("MRVL", "@AI", segments=segs))
        self.assertFalse(symbol_matches_filter("AAPL", "@AI", segments=segs))
        self.assertTrue(symbol_matches_filter("AAPL", "@NOPE", segments=segs))

    def test_live_define_keeps_first_ticker_after_equals(self):
        # Comma-split turns ``@CL=AMZN,GOOG`` into ``@CL=AMZN`` + ``GOOG``;
        # the RHS of the define token must still match AMZN.
        raw = "@CL=AMZN,GOOG"
        self.assertTrue(symbol_matches_filter("AMZN", raw))
        self.assertTrue(symbol_matches_filter("GOOG", raw))
        self.assertTrue(symbol_matches_filter("GOOGL", raw))
        self.assertFalse(symbol_matches_filter("AAPL", raw))
        self.assertEqual(expand_filter(raw, {}), "AMZN, GOOG")

    def test_exclude_only(self):
        self.assertTrue(symbol_matches_filter("AAPL", "-intc"))
        self.assertFalse(symbol_matches_filter("INTC", "-intc"))

    def test_cycle_safe_expand(self):
        segs = {"A": "@B", "B": "@A, mu"}
        expanded = expand_filter("@A", segs)
        self.assertIn("mu", expanded.lower())

    def test_merge_and_export(self):
        merged = merge_segments({"AI": "tsm"}, {"AI": "tsm, mr", "EU": "sap", "GONE": None})
        self.assertEqual(merged["AI"], "tsm, mr")
        self.assertEqual(merged["EU"], "sap")
        self.assertNotIn("GONE", merged)
        text = export_segments_text(merged)
        self.assertIn("@AI=tsm, mr", text)
        self.assertIn("@EU=sap", text)

    def test_starred_tokens(self):
        starred = {"NVDA"}
        self.assertTrue(symbol_matches_filter("NVDA", "*", starred=starred))
        self.assertFalse(symbol_matches_filter("AAPL", "*", starred=starred))
        self.assertFalse(symbol_matches_filter("AAPL", "aa, +*", starred=starred))
        self.assertTrue(symbol_matches_filter("NVDA", "nv, +*", starred=starred))


if __name__ == "__main__":
    unittest.main()
