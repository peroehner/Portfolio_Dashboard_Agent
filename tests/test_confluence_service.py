"""Unit tests for the Confluence agent — fusing the technical lenses (Phase 3).

Pure-function tests: a hand-built ``signals`` dict in, a fused confluence block
out. No network, no DB — the vote/aggregation logic is exercised deterministically.
"""
import unittest

from services.confluence_service import compute_confluence


def _signals(
    *,
    ma_stack="bullish",
    slope=20.0,
    cross="above",
    structure="uptrend (higher highs & higher lows)",
    macd_state="bullish",
    rsi=60.0,
    patterns=None,
    obv=5.0,
    vol_state="elevated",
    rvol=1.4,
    node="high",
):
    return {
        "price": 100.0,
        "trend": {
            "maStack": ma_stack,
            "slopePctPerYr": slope,
            "crossState": cross,
        },
        "swing": {"structure": structure},
        "momentum": {"macd": {"state": macd_state}, "rsi14": rsi, "rsiZone": "neutral"},
        "patterns": patterns or [],
        "volume": {"obvSlopePct": obv, "state": vol_state, "rvol": rvol},
        "volumeProfile": {"priceNode": {"node": node}},
    }


def _pattern(ptype, verdict, *, name="Double Bottom", confidence=0.7, adj=None):
    return {
        "name": name,
        "type": ptype,
        "confidence": confidence,
        "validation": {"verdict": verdict, "adjustedConfidence": adj},
    }


class BiasAggregationTests(unittest.TestCase):
    def test_all_bullish_lenses_yield_bullish(self):
        conf = compute_confluence(
            _signals(patterns=[_pattern("bullish", "confirmed", adj=0.7)])
        )
        self.assertIsNotNone(conf)
        self.assertEqual(conf["bias"], "Bullish")
        self.assertGreater(conf["score"], 0.45)
        self.assertEqual(conf["conflictCount"], 0)
        self.assertEqual(conf["strength"], "strong")
        self.assertEqual(conf["score100"], int(round((conf["score"] + 1) / 2 * 100)))

    def test_all_bearish_lenses_yield_bearish(self):
        conf = compute_confluence(
            _signals(
                ma_stack="bearish",
                slope=-20.0,
                cross="death",
                structure="downtrend (lower highs & lower lows)",
                macd_state="bearish",
                rsi=40.0,
                patterns=[_pattern("bearish", "confirmed", name="Double Top", adj=0.7)],
                obv=-5.0,
            )
        )
        self.assertEqual(conf["bias"], "Bearish")
        self.assertLess(conf["score"], -0.45)

    def test_conflict_is_listed(self):
        # Bullish trend/structure/momentum/volume but a confirmed bearish pattern.
        conf = compute_confluence(
            _signals(patterns=[_pattern("bearish", "confirmed", name="Double Top", adj=0.8)])
        )
        self.assertGreater(conf["score"], 0)  # majority still bullish
        labels = " ".join(conf["conflicts"])
        self.assertIn("Double Top", labels)
        self.assertGreaterEqual(conf["conflictCount"], 1)

    def test_mixed_when_signals_cancel(self):
        conf = compute_confluence(
            _signals(
                ma_stack="mixed",
                slope=0.0,
                cross="above",
                structure="range / mixed",
                macd_state=None,
                rsi=50.0,
                obv=0.0,
                vol_state="normal",
                node="medium",
            )
        )
        self.assertEqual(conf["bias"], "Mixed")
        self.assertLess(abs(conf["score"]), 0.15)


class VerdictWeightingTests(unittest.TestCase):
    @staticmethod
    def _pattern_weight(conf):
        for v in conf["votes"]:
            if v["agent"] == "pattern":
                return v["weight"]
        return 0.0

    def test_stale_pattern_barely_counts(self):
        strong = compute_confluence(
            _signals(patterns=[_pattern("bullish", "confirmed", adj=0.8)])
        )
        stale = compute_confluence(
            _signals(patterns=[_pattern("bullish", "stale", adj=0.8)])
        )
        # A confirmed pattern carries far more weight in the fusion than a stale one.
        self.assertGreater(self._pattern_weight(strong), self._pattern_weight(stale))
        # Stale is heavily discounted (verdict factor 0.05).
        self.assertLess(self._pattern_weight(stale), 0.2)

    def test_pattern_vote_skipped_when_neutral_type(self):
        conf = compute_confluence(
            _signals(patterns=[_pattern("neutral", "pending", name="Symmetrical Triangle")])
        )
        agents = {v["agent"] for v in conf["votes"]}
        self.assertNotIn("pattern", agents)


class RobustnessTests(unittest.TestCase):
    def test_none_signals_returns_none(self):
        self.assertIsNone(compute_confluence(None))

    def test_empty_signals_returns_none(self):
        self.assertIsNone(compute_confluence({}))

    def test_partial_signals_still_fuse(self):
        # Only a trend block available (chart path before other blocks exist).
        conf = compute_confluence({"trend": {"maStack": "bullish", "slopePctPerYr": 18.0}})
        self.assertIsNotNone(conf)
        self.assertEqual(conf["bias"] in ("Bullish", "Lean Bullish"), True)
        self.assertEqual(conf["totalSignals"], 1)


if __name__ == "__main__":
    unittest.main()
