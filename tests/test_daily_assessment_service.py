import os
import unittest
from unittest.mock import patch

import psycopg

from db_test_env import TEST_DATABASE_URL

if TEST_DATABASE_URL:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from db.database import (  # noqa: E402
    close_pool,
    get_bootstrap_user_id,
    get_connection,
    get_database_url,
    init_db,
    reset_bootstrap_user_cache,
    set_current_user_id,
)
from services.daily_assessment_service import run_daily_assessments, should_run_today  # noqa: E402
from services.portfolio_service import PortfolioService  # noqa: E402
from services.symbol_assessment_service import SymbolAssessmentService, utc_today_iso  # noqa: E402


def _db_available() -> bool:
    if not TEST_DATABASE_URL:
        return False
    try:
        with psycopg.connect(TEST_DATABASE_URL, connect_timeout=3):
            return True
    except Exception:
        return False


DB_AVAILABLE = _db_available()


def _reset_schema() -> None:
    close_pool()
    with psycopg.connect(get_database_url(), autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    reset_bootstrap_user_cache()
    init_db()


@unittest.skipUnless(DB_AVAILABLE, "TEST_DATABASE_URL not set or unreachable")
class DailyAssessmentServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        _reset_schema()
        set_current_user_id(get_bootstrap_user_id())
        PortfolioService().upsert_symbol("AAPL", {"target_price": 150.0})
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO symbol_market (symbol, current_price, updated_at)
                VALUES ('AAPL', 100.0, app_now_text())
                """
            )
            conn.commit()

    def test_should_run_today_when_not_yet_run(self) -> None:
        self.assertTrue(should_run_today())

    @patch.object(SymbolAssessmentService, "get_or_compute_today")
    def test_run_daily_assessments_marks_complete(self, mock_get) -> None:
        mock_get.return_value = {"fromCache": False, "action": "watch"}

        first = run_daily_assessments(["AAPL"])
        second = run_daily_assessments(["AAPL"])

        self.assertEqual(first["computed"], 1)
        self.assertEqual(first["date"], utc_today_iso())
        self.assertTrue(second.get("skipped"))
        self.assertEqual(second.get("reason"), "already_ran")
        self.assertFalse(should_run_today())
        mock_get.assert_called_once_with("AAPL")

    def test_symbols_table_has_no_market_columns(self) -> None:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'symbols'
                ORDER BY column_name
                """
            ).fetchall()
        columns = {row["column_name"] for row in rows}
        self.assertNotIn("current_price", columns)
        self.assertNotIn("analyst_target_1y", columns)
        self.assertIn("target_price", columns)


if __name__ == "__main__":
    unittest.main()
