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
from services.enrichment_warmer_service import build_warm_priority_queue  # noqa: E402
from services.portfolio_service import PortfolioService  # noqa: E402


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
class EnrichmentWarmerPriorityTests(unittest.TestCase):
    def setUp(self) -> None:
        _reset_schema()
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO users (email, name) VALUES (%s, %s), (%s, %s)",
                ("alice@example.com", "Alice", "bob@example.com", "Bob"),
            )
            rows = conn.execute("SELECT id, email FROM users ORDER BY email").fetchall()
            conn.commit()
        self.alice_id = next(row["id"] for row in rows if row["email"] == "alice@example.com")
        self.bob_id = next(row["id"] for row in rows if row["email"] == "bob@example.com")

    def test_starred_symbols_rank_first(self) -> None:
        set_current_user_id(self.alice_id)
        PortfolioService().upsert_symbol("ZZZ", {"target_price": 1.0})
        PortfolioService().upsert_symbol("AAA", {"target_price": 2.0})
        PortfolioService().set_symbol_starred("ZZZ", True)

        set_current_user_id(self.bob_id)
        PortfolioService().upsert_symbol("MMM", {"target_price": 3.0})
        PortfolioService().sync_starred_symbols(["MMM"])

        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO holdings (user_id, symbol, quantity)
                VALUES (%s, 'AAA', 10)
                ON CONFLICT (user_id, symbol) DO UPDATE SET quantity = EXCLUDED.quantity
                """,
                (self.alice_id,),
            )
            conn.commit()

        queue = build_warm_priority_queue()
        self.assertEqual(queue[:2], ["MMM", "ZZZ"])
        self.assertIn("AAA", queue[2:])

    def test_sync_starred_symbols_scoped_to_user(self) -> None:
        set_current_user_id(self.alice_id)
        PortfolioService().upsert_symbol("AAPL", {"target_price": 150.0})
        PortfolioService().sync_starred_symbols(["AAPL"])

        set_current_user_id(self.bob_id)
        PortfolioService().upsert_symbol("AAPL", {"target_price": 160.0})
        PortfolioService().sync_starred_symbols([])

        set_current_user_id(self.alice_id)
        self.assertEqual(PortfolioService().list_starred_symbols(), ["AAPL"])
        symbol = PortfolioService().get_symbol("AAPL")
        assert symbol is not None
        self.assertTrue(symbol["isStarred"])

        set_current_user_id(self.bob_id)
        self.assertEqual(PortfolioService().list_starred_symbols(), [])
        symbol = PortfolioService().get_symbol("AAPL")
        assert symbol is not None
        self.assertFalse(symbol["isStarred"])


if __name__ == "__main__":
    unittest.main()
