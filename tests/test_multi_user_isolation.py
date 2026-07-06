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
class MultiUserPortfolioIsolationTests(unittest.TestCase):
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

    def test_list_symbols_scoped_per_user(self) -> None:
        set_current_user_id(self.alice_id)
        PortfolioService().upsert_symbol("AAPL", {"target_price": 150.0})
        PortfolioService().upsert_symbol("MSFT", {"target_price": 300.0})

        set_current_user_id(self.bob_id)
        PortfolioService().upsert_symbol("NVDA", {"target_price": 180.0})

        set_current_user_id(self.alice_id)
        alice_symbols = {s["symbol"] for s in PortfolioService().list_symbols()}
        self.assertEqual(alice_symbols, {"AAPL", "MSFT"})

        set_current_user_id(self.bob_id)
        bob_symbols = {s["symbol"] for s in PortfolioService().list_symbols()}
        self.assertEqual(bob_symbols, {"NVDA"})

    def test_clear_portfolio_does_not_touch_other_users(self) -> None:
        set_current_user_id(self.alice_id)
        PortfolioService().upsert_symbol("AAPL", {"target_price": 150.0})
        set_current_user_id(self.bob_id)
        PortfolioService().upsert_symbol("NVDA", {"target_price": 180.0})

        PortfolioService().clear_portfolio()

        self.assertEqual(PortfolioService().list_symbols(), [])
        set_current_user_id(self.alice_id)
        self.assertEqual(len(PortfolioService().list_symbols()), 1)


if __name__ == "__main__":
    unittest.main()
