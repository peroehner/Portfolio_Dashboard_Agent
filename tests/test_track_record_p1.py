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
    fit_band_label,
    strength_from_proposal,
    _direction_adjusted_return,
    _finalize,
    _new_bucket,
    _accumulate,
)


def _db_available() -> bool:
    if not TEST_DATABASE_URL:
        return False
    try:
        with psycopg.connect(TEST_DATABASE_URL, connect_timeout=3):
            return True
    except Exception:
        return False


DB_AVAILABLE = _db_available()


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
        self.assertEqual(fit_band_label(70), "strong")
        self.assertEqual(fit_band_label(50), "mid")
        self.assertEqual(fit_band_label(20), "weak")
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


if __name__ == "__main__":
    unittest.main()
