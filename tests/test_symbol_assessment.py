import os
import unittest
from unittest.mock import MagicMock, patch

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


MOCK_BASE_RESULT = {
    "action": "watch",
    "confidence": "medium",
    "rationale": "Shared market view.",
    "factors": ["Analyst upside 35%."],
    "provider": "rules",
    "actionSource": "rules_fallback",
}


@unittest.skipUnless(DB_AVAILABLE, "TEST_DATABASE_URL not set or unreachable")
class SymbolAssessmentServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        _reset_schema()
        set_current_user_id(get_bootstrap_user_id())
        PortfolioService().upsert_symbol("AAPL", {"current_price": 100.0})
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO symbol_market (symbol, current_price, analyst_target_1y, updated_at)
                VALUES ('AAPL', 100.0, 135.0, app_now_text())
                ON CONFLICT (symbol) DO UPDATE SET
                    current_price = EXCLUDED.current_price,
                    analyst_target_1y = EXCLUDED.analyst_target_1y
                """
            )
            conn.commit()

    @patch.object(SymbolAssessmentService, "build_base_context")
    def test_get_or_compute_caches_per_day(self, mock_context) -> None:
        mock_context.return_value = {
            "symbol": "AAPL",
            "currentPrice": 100.0,
            "analystTarget1y": 135.0,
            "screening": {"upsidePct": 35.0},
            "fundamentals": {},
            "recentNews": [],
            "technical": None,
            "fibLevels": [],
        }
        service = SymbolAssessmentService()
        service.llm_client = MagicMock()
        service.llm_client.generate_base_assessment.return_value = dict(MOCK_BASE_RESULT)

        first = service.get_or_compute_today("AAPL")
        second = service.get_or_compute_today("AAPL")

        self.assertFalse(first["fromCache"])
        self.assertTrue(second["fromCache"])
        self.assertEqual(first["action"], "watch")
        service.llm_client.generate_base_assessment.assert_called_once()

        with get_connection() as conn:
            count = conn.execute(
                "SELECT COUNT(*) AS n FROM symbol_assessment WHERE symbol = %s AND as_of_date = %s",
                ("AAPL", utc_today_iso()),
            ).fetchone()["n"]
        self.assertEqual(int(count), 1)


if __name__ == "__main__":
    unittest.main()
