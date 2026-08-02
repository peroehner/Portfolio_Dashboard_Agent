"""Unit tests for Agent Signal Record episode scoring (P0)."""

import os
import unittest
from unittest.mock import MagicMock

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
from services.track_record_service import (  # noqa: E402
    TrackRecordService,
    episode_flip_targets,
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


class EpisodeFlipTargetTests(unittest.TestCase):
    def test_pairs_buy_then_sell(self) -> None:
        rows = [
            {"id": 1, "label": "buy"},
            {"id": 2, "label": "sell"},
        ]
        pairs = episode_flip_targets(rows)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0][0], 1)
        self.assertEqual(pairs[0][1]["id"], 2)

    def test_same_action_no_flip(self) -> None:
        rows = [
            {"id": 1, "label": "buy"},
            {"id": 2, "label": "buy"},
        ]
        self.assertEqual(episode_flip_targets(rows), [])

    def test_chain_buy_sell_buy(self) -> None:
        rows = [
            {"id": 1, "label": "buy"},
            {"id": 2, "label": "sell"},
            {"id": 3, "label": "buy"},
        ]
        pairs = episode_flip_targets(rows)
        self.assertEqual([(p[0], p[1]["id"]) for p in pairs], [(1, 2), (2, 3)])

    def test_classify_bullish(self) -> None:
        self.assertEqual(TrackRecordService._classify("bullish", 5.0), "win")
        self.assertEqual(TrackRecordService._classify("bullish", -5.0), "loss")
        self.assertEqual(TrackRecordService._classify("bullish", 0.5), "neutral")

    def test_classify_bearish(self) -> None:
        self.assertEqual(TrackRecordService._classify("bearish", -5.0), "win")
        self.assertEqual(TrackRecordService._classify("bearish", 5.0), "loss")


def _reset_schema() -> None:
    close_pool()
    with psycopg.connect(get_database_url(), autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    reset_bootstrap_user_cache()
    init_db()


@unittest.skipUnless(DB_AVAILABLE, "TEST_DATABASE_URL not set or unreachable")
class RecommendationEpisodeDbTests(unittest.TestCase):
    def setUp(self) -> None:
        _reset_schema()
        with get_connection() as conn:
            row = conn.execute(
                "INSERT INTO users (email, name) VALUES (%s, %s) RETURNING id",
                ("track@example.com", "Track"),
            ).fetchone()
            self.user_id = int(row["id"])
            conn.execute(
                """
                INSERT INTO symbols (user_id, symbol, target_price)
                VALUES (%s, %s, %s)
                """,
                (self.user_id, "AAPL", 200.0),
            )
            conn.commit()
        set_current_user_id(self.user_id)
        self.svc = TrackRecordService()
        self.svc.portfolio_service = MagicMock()
        self.svc.portfolio_service.list_symbols.return_value = [
            {"symbol": "AAPL", "currentPrice": 110.0}
        ]

    def _insert_rec(
        self,
        *,
        label: str,
        direction: str,
        entry: float,
        captured_at: str,
        eval_due_at: str,
        outcome: str | None = None,
        eval_price: float | None = None,
        return_pct: float | None = None,
    ) -> int:
        with get_connection() as conn:
            row = conn.execute(
                """
                INSERT INTO signal_outcomes (
                    user_id, symbol, kind, label, direction, entry_price,
                    horizon_days, captured_at, eval_due_at, outcome, eval_price,
                    return_pct, evaluated_at
                )
                VALUES (
                    %s, 'AAPL', 'recommendation', %s, %s, %s, 21, %s, %s,
                    %s, %s, %s, %s
                )
                RETURNING id
                """,
                (
                    self.user_id,
                    label,
                    direction,
                    entry,
                    captured_at,
                    eval_due_at,
                    outcome,
                    eval_price,
                    return_pct,
                    "2026-07-20 00:00:00" if outcome else None,
                ),
            ).fetchone()
            conn.commit()
            return int(row["id"])

    def test_reconcile_early_closes_buy_at_sell_entry(self) -> None:
        # Buy at 100, later Sell at 108 — Buy should win on +8%, not wait for horizon.
        buy_id = self._insert_rec(
            label="buy",
            direction="bullish",
            entry=100.0,
            captured_at="2026-07-01 00:00:00",
            eval_due_at="2026-07-22 00:00:00",
        )
        self._insert_rec(
            label="sell",
            direction="bearish",
            entry=108.0,
            captured_at="2026-07-10 00:00:00",
            eval_due_at="2026-07-31 00:00:00",
        )
        updated = self.svc.reconcile_recommendation_episodes()
        self.assertGreaterEqual(updated, 1)
        with get_connection() as conn:
            buy = conn.execute(
                "SELECT outcome, eval_price, return_pct FROM signal_outcomes WHERE id = %s",
                (buy_id,),
            ).fetchone()
        self.assertEqual(buy["outcome"], "win")
        self.assertAlmostEqual(float(buy["eval_price"]), 108.0)
        self.assertAlmostEqual(float(buy["return_pct"]), 8.0)

    def test_reconcile_rewrites_wrong_horizon_score(self) -> None:
        # Buy was wrongly scored at day-21 price 90 (loss) even though Sell
        # flipped at 108 on day 10 — rewrite to episode win.
        buy_id = self._insert_rec(
            label="buy",
            direction="bullish",
            entry=100.0,
            captured_at="2026-07-01 00:00:00",
            eval_due_at="2026-07-22 00:00:00",
            outcome="loss",
            eval_price=90.0,
            return_pct=-10.0,
        )
        self._insert_rec(
            label="sell",
            direction="bearish",
            entry=108.0,
            captured_at="2026-07-10 00:00:00",
            eval_due_at="2026-07-31 00:00:00",
        )
        self.svc.reconcile_recommendation_episodes()
        with get_connection() as conn:
            buy = conn.execute(
                "SELECT outcome, eval_price, return_pct FROM signal_outcomes WHERE id = %s",
                (buy_id,),
            ).fetchone()
        self.assertEqual(buy["outcome"], "win")
        self.assertAlmostEqual(float(buy["eval_price"]), 108.0)

    def test_early_close_on_capture_helper(self) -> None:
        buy_id = self._insert_rec(
            label="buy",
            direction="bullish",
            entry=100.0,
            captured_at="2026-07-01 00:00:00",
            eval_due_at="2026-07-22 00:00:00",
        )
        with get_connection() as conn:
            closed = self.svc.early_close_conflicting_recommendations(
                conn,
                self.user_id,
                "AAPL",
                new_label="sell",
                eval_price=95.0,
                evaluated_at="2026-07-05 12:00:00",
            )
            conn.commit()
        self.assertEqual(closed, 1)
        with get_connection() as conn:
            buy = conn.execute(
                "SELECT outcome, return_pct FROM signal_outcomes WHERE id = %s",
                (buy_id,),
            ).fetchone()
        self.assertEqual(buy["outcome"], "loss")
        self.assertAlmostEqual(float(buy["return_pct"]), -5.0)


if __name__ == "__main__":
    unittest.main()
