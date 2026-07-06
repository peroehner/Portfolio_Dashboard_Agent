import os
import unittest

import psycopg

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
if TEST_DATABASE_URL:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from db.database import (  # noqa: E402
    close_pool,
    get_connection,
    get_database_url,
    init_db,
    list_distinct_symbols,
    reset_bootstrap_user_cache,
    set_current_user_id,
)
from services.market_data_service import MarketDataService  # noqa: E402
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


class _FakeEngine:
    def fetch_market_quotes(self, tickers, include_analyst_targets=True):
        return {
            ticker: {
                "currentPrice": 101.5,
                "dayChangePct": 1.2,
                "priceAsOf": "2026-07-06",
                "analystTarget1y": 120.0 if include_analyst_targets else None,
                "analystTargetLow": 110.0 if include_analyst_targets else None,
                "analystTargetHigh": 130.0 if include_analyst_targets else None,
            }
            for ticker in tickers
        }


@unittest.skipUnless(DB_AVAILABLE, "TEST_DATABASE_URL not set or unreachable")
class MarketDataServiceTests(unittest.TestCase):
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
        for user_id in (self.alice_id, self.bob_id):
            set_current_user_id(user_id)
            PortfolioService().upsert_symbol(
                "AAPL",
                {"target_price": 150.0 if user_id == self.alice_id else 160.0},
            )

    def test_sync_quotes_deduplicates_across_users(self) -> None:
        self.assertEqual(list_distinct_symbols(), ["AAPL"])
        result = MarketDataService().sync_quotes(_FakeEngine(), ["AAPL"])
        self.assertEqual(result["updated"], 1)

        with get_connection() as conn:
            market = conn.execute(
                "SELECT current_price, analyst_target_1y FROM symbol_market WHERE symbol = %s",
                ("AAPL",),
            ).fetchone()
            user_rows = conn.execute(
                "SELECT user_id, current_price, target_price FROM symbols WHERE symbol = %s ORDER BY user_id",
                ("AAPL",),
            ).fetchall()

        self.assertIsNotNone(market)
        self.assertEqual(market["current_price"], 101.5)
        self.assertEqual(market["analyst_target_1y"], 120.0)
        self.assertEqual(len(user_rows), 2)
        self.assertTrue(all(row["current_price"] == 101.5 for row in user_rows))
        targets = sorted(row["target_price"] for row in user_rows)
        self.assertEqual(targets, [150.0, 160.0])

    def test_portfolio_reads_prefer_symbol_market(self) -> None:
        MarketDataService().sync_quotes(_FakeEngine(), ["AAPL"])
        set_current_user_id(self.alice_id)
        symbol = PortfolioService().get_symbol("AAPL")
        self.assertIsNotNone(symbol)
        assert symbol is not None
        self.assertEqual(symbol["currentPrice"], 101.5)
        self.assertEqual(symbol["targetPrice"], 150.0)


if __name__ == "__main__":
    unittest.main()
