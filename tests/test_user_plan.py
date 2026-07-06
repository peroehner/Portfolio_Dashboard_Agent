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
from services.plan_service import (  # noqa: E402
    DEFAULT_PLAN,
    get_user_plan,
    normalize_plan,
    set_user_plan,
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


def _reset_schema() -> None:
    close_pool()
    os.environ.pop("USER_PLAN_OVERRIDE", None)
    with psycopg.connect(get_database_url(), autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    reset_bootstrap_user_cache()
    init_db()


@unittest.skipUnless(DB_AVAILABLE, "TEST_DATABASE_URL not set or unreachable")
class UserPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        _reset_schema()
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO users (email, name) VALUES (%s, %s) RETURNING id",
                ("alice@example.com", "Alice"),
            )
            row = conn.execute(
                "SELECT id FROM users WHERE email = %s", ("alice@example.com",)
            ).fetchone()
            conn.commit()
        self.user_id = int(row["id"])
        set_current_user_id(self.user_id)

    def test_new_user_defaults_to_free(self) -> None:
        self.assertEqual(get_user_plan(), DEFAULT_PLAN)
        with get_connection() as conn:
            row = conn.execute(
                "SELECT plan FROM users WHERE id = %s", (self.user_id,)
            ).fetchone()
        self.assertEqual(row["plan"], "free")

    def test_set_and_get_plan(self) -> None:
        self.assertEqual(set_user_plan("standard"), "standard")
        self.assertEqual(get_user_plan(), "standard")
        self.assertEqual(set_user_plan("pro"), "pro")
        self.assertEqual(get_user_plan(), "pro")

    def test_normalize_plan_rejects_invalid(self) -> None:
        with self.assertRaises(ValueError):
            normalize_plan("enterprise")

    def test_plan_override_env(self) -> None:
        os.environ["USER_PLAN_OVERRIDE"] = "pro"
        self.assertEqual(get_user_plan(), "pro")
        # DB still free until Stripe updates it
        with get_connection() as conn:
            row = conn.execute(
                "SELECT plan FROM users WHERE id = %s", (self.user_id,)
            ).fetchone()
        self.assertEqual(row["plan"], "free")


if __name__ == "__main__":
    unittest.main()
