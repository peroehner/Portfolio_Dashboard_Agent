"""Unit tests for Signal Record P1 — strength metadata + Fib bet helpers."""

import os
import unittest

import psycopg

from db_test_env import TEST_DATABASE_URL

if TEST_DATABASE_URL:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from db.database import (  # noqa: E402
    close_pool,
    get_connection,
    get_database_url,
    init_db,
    reset_bootstrap_user_cache,
    set_current_user_id,
)
from services.fib_roles import fib_bet_direction, fib_bet_label  # noqa: E402
from services.track_record_service import (  # noqa: E402
    TrackRecordService,
    conflict_bucket_label,
    confluence_outcome_meta,
    era_cutoff_prefix,
    fit_band_label,
    strength_from_proposal,
    _direction_adjusted_return,
    _finalize,
    _new_bucket,
    _accumulate,
)
import services.track_record_service as track_record_mod  # noqa: E402


def _db_available() -> bool:
    if not TEST_DATABASE_URL:
        return False
    try:
        with psycopg.connect(TEST_DATABASE_URL, connect_timeout=3):
            return True
    except Exception:
        return False


DB_AVAILABLE = _db_available()


class EraCutoffHelperTests(unittest.TestCase):
    def test_default_prefix_is_p0_ship_day(self) -> None:
        self.assertEqual(era_cutoff_prefix(), "2026-08-02")

    def test_empty_disables_filter(self) -> None:
        prev = track_record_mod.TRACK_RECORD_ERA_CUTOFF_DATE
        try:
            track_record_mod.TRACK_RECORD_ERA_CUTOFF_DATE = ""
            self.assertIsNone(era_cutoff_prefix())
        finally:
            track_record_mod.TRACK_RECORD_ERA_CUTOFF_DATE = prev

    def test_timestamp_env_uses_date_prefix(self) -> None:
        prev = track_record_mod.TRACK_RECORD_ERA_CUTOFF_DATE
        try:
            track_record_mod.TRACK_RECORD_ERA_CUTOFF_DATE = "2026-08-02 13:34:54"
            self.assertEqual(era_cutoff_prefix(), "2026-08-02")
        finally:
            track_record_mod.TRACK_RECORD_ERA_CUTOFF_DATE = prev


class FibBetHelperTests(unittest.TestCase):
    def test_direction_from_side(self) -> None:
        self.assertEqual(fib_bet_direction("above"), "bullish")
        self.assertEqual(fib_bet_direction("below"), "bearish")
        self.assertEqual(fib_bet_direction(None), "neutral")

    def test_label(self) -> None:
        self.assertEqual(
            fib_bet_label({"label": "61.8%", "roleName": "Golden Pocket"}),
            "61.8% Golden Pocket",
        )
        self.assertEqual(
            fib_bet_label({"label": "Golden Pocket", "roleName": "Golden Pocket"}),
            "Golden Pocket",
        )


class StrengthHelperTests(unittest.TestCase):
    def test_strength_from_proposal(self) -> None:
        conf, fit, band = strength_from_proposal(
            {
                "confidence": "high",
                "scores": {"total": 72},
                "bandBias": {"code": "buy"},
            },
            "medium",
        )
        self.assertEqual(conf, "medium")  # explicit arg wins
        self.assertEqual(fit, 72.0)
        self.assertEqual(band, "buy")

    def test_fit_band_label(self) -> None:
        # Same cuts as Conf base: ≥75 high · ≥35 medium · else low (raw; no soften).
        self.assertEqual(fit_band_label(80), "high")
        self.assertEqual(fit_band_label(70), "medium")
        self.assertEqual(fit_band_label(35), "medium")
        self.assertEqual(fit_band_label(34), "low")
        self.assertEqual(fit_band_label(20), "low")
        self.assertEqual(fit_band_label(None), "unknown")

    def test_direction_adjusted_return(self) -> None:
        self.assertEqual(_direction_adjusted_return("bullish", 5.0), 5.0)
        self.assertEqual(_direction_adjusted_return("bearish", -5.0), 5.0)
        self.assertEqual(_direction_adjusted_return("bearish", 5.0), -5.0)
        self.assertEqual(_direction_adjusted_return("neutral", 3.0), 0.0)

    def test_calibrated_hit_rate_weights_high_confidence(self) -> None:
        bucket = _new_bucket()
        # One high-confidence win vs one low-confidence loss → calibrated > plain hit
        _accumulate(
            bucket,
            {
                "outcome": "win",
                "return_pct": 4.0,
                "direction": "bullish",
                "confidence": "high",
                "fit_total": 80.0,
            },
        )
        _accumulate(
            bucket,
            {
                "outcome": "loss",
                "return_pct": -4.0,
                "direction": "bullish",
                "confidence": "low",
                "fit_total": 20.0,
            },
        )
        out = _finalize(bucket)
        self.assertEqual(out["hitRate"], 50.0)
        self.assertGreater(out["calibratedHitRate"], out["hitRate"])
        self.assertEqual(out["avgReturnAdj"], 0.0)


class ConfluenceMetaTests(unittest.TestCase):
    def test_lean_vs_strong_band(self) -> None:
        lean = confluence_outcome_meta(
            {
                "bias": "Lean Bearish",
                "score": -0.22,
                "agreeCount": 2,
                "conflictCount": 1,
                "strength": "moderate",
            }
        )
        self.assertEqual(lean["confluenceBand"], "lean")
        self.assertEqual(lean["confluenceScore"], -0.22)
        self.assertEqual(lean["agreeCount"], 2)
        self.assertEqual(lean["conflictCount"], 1)
        self.assertEqual(lean["signalStrength"], "moderate")

        strong = confluence_outcome_meta(
            {
                "bias": "Bullish",
                "score": 0.61,
                "agreeCount": 4,
                "conflictCount": 0,
                "strength": "strong",
            }
        )
        self.assertEqual(strong["confluenceBand"], "strong")
        self.assertEqual(strong["conflictCount"], 0)

    def test_mixed_or_empty_is_empty_meta(self) -> None:
        empty = confluence_outcome_meta({"bias": "Mixed", "score": 0.05})
        self.assertIsNone(empty["confluenceBand"])
        none_meta = confluence_outcome_meta(None)
        self.assertIsNone(none_meta["confluenceBand"])

    def test_conflict_bucket_label(self) -> None:
        self.assertEqual(conflict_bucket_label(0), "clean")
        self.assertEqual(conflict_bucket_label(2), "contested")
        self.assertEqual(conflict_bucket_label(None), "unknown")


def _reset_schema() -> None:
    close_pool()
    with psycopg.connect(get_database_url(), autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    reset_bootstrap_user_cache()
    init_db()


@unittest.skipUnless(DB_AVAILABLE, "TEST_DATABASE_URL not set or unreachable")
class FibCaptureDbTests(unittest.TestCase):
    def setUp(self) -> None:
        _reset_schema()
        with get_connection() as conn:
            row = conn.execute(
                "INSERT INTO users (email, name) VALUES (%s, %s) RETURNING id",
                ("fib@example.com", "Fib"),
            ).fetchone()
            self.user_id = int(row["id"])
            conn.execute(
                "INSERT INTO symbols (user_id, symbol) VALUES (%s, %s)",
                (self.user_id, "MSFT"),
            )
            conn.commit()
        set_current_user_id(self.user_id)
        self.svc = TrackRecordService()

    def test_capture_fib_dedup(self) -> None:
        ok = self.svc.capture_fib_proximity_bet(
            user_id=self.user_id,
            symbol="MSFT",
            entry_price=400.0,
            label="61.8% Golden Pocket",
            direction="bullish",
            alert_id=1,
        )
        self.assertTrue(ok)
        again = self.svc.capture_fib_proximity_bet(
            user_id=self.user_id,
            symbol="MSFT",
            entry_price=401.0,
            label="61.8% Golden Pocket",
            direction="bullish",
            alert_id=2,
        )
        self.assertFalse(again)
        with get_connection() as conn:
            n = conn.execute(
                "SELECT COUNT(*) AS n FROM signal_outcomes WHERE kind = 'fib'"
            ).fetchone()["n"]
        self.assertEqual(n, 1)


@unittest.skipUnless(DB_AVAILABLE, "TEST_DATABASE_URL not set or unreachable")
class EraCutoffSummaryDbTests(unittest.TestCase):
    def setUp(self) -> None:
        _reset_schema()
        with get_connection() as conn:
            row = conn.execute(
                "INSERT INTO users (email, name) VALUES (%s, %s) RETURNING id",
                ("era@example.com", "Era"),
            ).fetchone()
            self.user_id = int(row["id"])
            conn.execute(
                "INSERT INTO symbols (user_id, symbol) VALUES (%s, %s)",
                (self.user_id, "AAPL"),
            )
            conn.commit()
        set_current_user_id(self.user_id)
        self.svc = TrackRecordService()
        # Avoid side effects from reconcile/evaluate during summary tests.
        self.svc.reconcile_recommendation_episodes = lambda: 0  # type: ignore[method-assign]
        self.svc.backfill_recommendation_strength = lambda: 0  # type: ignore[method-assign]
        self.svc.evaluate_due = lambda: 0  # type: ignore[method-assign]

    def _insert_outcome(self, *, captured_at: str, outcome: str = "win") -> None:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO signal_outcomes (
                    user_id, symbol, kind, label, direction, entry_price,
                    horizon_days, captured_at, eval_due_at, outcome, return_pct,
                    evaluated_at
                )
                VALUES (
                    %s, 'AAPL', 'recommendation', 'buy', 'bullish', 100.0,
                    21, %s, %s, %s, 5.0, %s
                )
                """,
                (
                    self.user_id,
                    captured_at,
                    captured_at,
                    outcome,
                    captured_at,
                ),
            )
            conn.commit()

    def test_summary_excludes_pre_era_rows(self) -> None:
        self._insert_outcome(captured_at="2026-07-15 12:00:00")  # pre-era
        self._insert_outcome(captured_at="2026-08-02 00:00:00")  # on cutoff
        self._insert_outcome(captured_at="2026-08-10 09:00:00")  # post-era
        summary = self.svc.get_summary()
        self.assertEqual(summary["eraCutoffDate"], "2026-08-02")
        self.assertEqual(summary["excludedPreEra"], 1)
        self.assertEqual(summary["overall"]["count"], 2)
        self.assertEqual(summary["overall"]["wins"], 2)

    def test_empty_cutoff_includes_all_rows(self) -> None:
        self._insert_outcome(captured_at="2026-07-15 12:00:00")
        self._insert_outcome(captured_at="2026-08-10 09:00:00")
        prev = track_record_mod.TRACK_RECORD_ERA_CUTOFF_DATE
        try:
            track_record_mod.TRACK_RECORD_ERA_CUTOFF_DATE = ""
            summary = self.svc.get_summary()
            self.assertIsNone(summary["eraCutoffDate"])
            self.assertEqual(summary["excludedPreEra"], 0)
            self.assertEqual(summary["overall"]["count"], 2)
        finally:
            track_record_mod.TRACK_RECORD_ERA_CUTOFF_DATE = prev


if __name__ == "__main__":
    unittest.main()
