import os
import unittest
from unittest.mock import patch

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
from services.assessment_service import AssessmentService  # noqa: E402
from services.import_service import ImportService  # noqa: E402
from services.notes_service import NotesService  # noqa: E402
from services.plan_service import (  # noqa: E402
    PlanLimitExceeded,
    ensure_can_manual_ai_action,
    get_plan_limits,
    record_manual_ai_action,
    set_user_plan,
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
    os.environ.pop("USER_PLAN_OVERRIDE", None)
    with psycopg.connect(get_database_url(), autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    reset_bootstrap_user_cache()
    init_db()


@unittest.skipUnless(DB_AVAILABLE, "TEST_DATABASE_URL not set or unreachable")
class PlanLimitsTests(unittest.TestCase):
    def setUp(self) -> None:
        _reset_schema()
        os.environ["NOTE_AUTOSYNTH"] = "0"
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
        set_user_plan("free", self.user_id)

    def test_free_plan_limits(self) -> None:
        limits = get_plan_limits("free")
        self.assertEqual(limits.max_symbols, 10)
        self.assertEqual(limits.manual_ai_actions_per_day, 6)

    def test_standard_plan_limits(self) -> None:
        limits = get_plan_limits("standard")
        self.assertEqual(limits.max_symbols, 50)
        self.assertIsNone(limits.manual_ai_actions_per_day)

    def test_symbol_limit_blocks_eleventh_symbol(self) -> None:
        portfolio = PortfolioService()
        for index in range(10):
            portfolio.upsert_symbol(f"S{index:02d}", {"target_price": 100.0})
        with self.assertRaises(PlanLimitExceeded) as ctx:
            portfolio.upsert_symbol("S10", {"target_price": 100.0})
        self.assertEqual(ctx.exception.code, "symbol_limit")

    def test_symbol_limit_allows_update_of_existing(self) -> None:
        portfolio = PortfolioService()
        for index in range(10):
            portfolio.upsert_symbol(f"S{index:02d}", {"target_price": 100.0})
        portfolio.upsert_symbol("S00", {"target_price": 120.0})

    def test_import_rejects_batch_over_symbol_limit(self) -> None:
        payload = {f"S{index:02d}": {"targetPrice": 100.0} for index in range(11)}
        with self.assertRaises(PlanLimitExceeded):
            ImportService().import_payload(payload, mode="merge")

    def test_note_synthesis_daily_limit(self) -> None:
        portfolio = PortfolioService()
        portfolio.upsert_symbol("AAPL", {"target_price": 150.0})
        notes = NotesService()
        for index in range(5):
            note = notes.add_note("AAPL", {"text": f"note {index}"})
            with patch.object(
                notes.llm_client,
                "synthesize_note",
                return_value={"summary": f"synth {index}", "provider": "rules"},
            ):
                notes.synthesize_note("AAPL", note["id"], force=True)
        with patch.object(
            notes.llm_client,
            "synthesize_note",
            return_value={"summary": "sixth", "provider": "rules"},
        ):
            notes.synthesize_note(
                "AAPL",
                notes.add_note("AAPL", {"text": "sixth"})["id"],
                force=True,
            )
        with patch.object(
            notes.llm_client,
            "synthesize_note",
            return_value={"summary": "seventh", "provider": "rules"},
        ):
            with self.assertRaises(PlanLimitExceeded) as ctx:
                notes.synthesize_note(
                    "AAPL",
                    notes.add_note("AAPL", {"text": "seventh"})["id"],
                    force=True,
                )
        self.assertEqual(ctx.exception.code, "manual_ai_actions_limit")

    def test_assess_all_daily_limit(self) -> None:
        PortfolioService().upsert_symbol("AAPL", {"target_price": 150.0})
        service = AssessmentService()
        fake_result = {
            "action": "hold",
            "confidence": "medium",
            "rationale": "test",
            "factors": [],
            "provider": "rules",
        }
        fake_context = {"symbol": "AAPL"}
        for _ in range(6):
            record_manual_ai_action(self.user_id)
        with patch.object(service, "_compute_assessment", return_value=(fake_result, fake_context)):
            with self.assertRaises(PlanLimitExceeded) as ctx:
                service.assess_portfolio()
        self.assertEqual(ctx.exception.code, "manual_ai_actions_limit")

    def test_pro_plan_has_no_symbol_cap(self) -> None:
        set_user_plan("pro", self.user_id)
        portfolio = PortfolioService()
        for index in range(12):
            portfolio.upsert_symbol(f"S{index:02d}", {"target_price": 100.0})
        self.assertEqual(len(portfolio.list_symbols()), 12)

    def test_standard_allows_unlimited_synthesis(self) -> None:
        set_user_plan("standard", self.user_id)
        for _ in range(6):
            ensure_can_manual_ai_action(self.user_id)
            record_manual_ai_action(self.user_id)

    def test_single_symbol_assess_not_gated(self) -> None:
        set_user_plan("standard", self.user_id)
        PortfolioService().upsert_symbol("AAPL", {"target_price": 150.0})
        record_manual_ai_action(self.user_id)
        service = AssessmentService()
        fake_result = {
            "action": "hold",
            "confidence": "medium",
            "rationale": "test",
            "factors": [],
            "provider": "rules",
        }
        fake_context = {"symbol": "AAPL"}
        with patch.object(service, "_compute_assessment", return_value=(fake_result, fake_context)):
            service.assess_symbol("AAPL")
            service.assess_symbol("AAPL")


if __name__ == "__main__":
    unittest.main()
