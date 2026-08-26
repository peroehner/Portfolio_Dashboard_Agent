"""Multi-symbol note links + relevantSymbols normalization."""

from __future__ import annotations

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
from services.llm_client import LLMClient  # noqa: E402
from services.notes_service import NotesService  # noqa: E402


class RelevantSymbolsNormalizeTests(unittest.TestCase):
    def test_intersects_portfolio_and_requires_reason(self):
        portfolio = {"AMZN", "GOOG", "AAPL"}
        raw = [
            {"symbol": "amzn", "reason": "Cloud spend thesis"},
            {"symbol": "GOOG", "reason": ""},  # drop — no reason
            {"symbol": "MSFT", "reason": "Not in portfolio"},  # drop
            "AAPL",  # drop — string without reason
            {"symbol": "goog", "reason": "Ads / AI overlap"},  # dedupe after first empty GOOG
        ]
        out = LLMClient._normalize_relevant_symbols(raw, portfolio)
        self.assertEqual(
            out,
            [
                {"symbol": "AMZN", "reason": "Cloud spend thesis"},
                {"symbol": "GOOG", "reason": "Ads / AI overlap"},
            ],
        )

    def test_normalize_synthesis_includes_relevant_symbols(self):
        client = LLMClient()
        result = client._normalize_synthesis(
            {
                "summary": "Multi-name AI spend.",
                "sentiment": "bullish",
                "growthTrajectory": [],
                "revenueProjections": [],
                "catalystsToWatch": [],
                "relevantSymbols": [
                    {"symbol": "GOOG", "reason": "Ads leverage"},
                    {"symbol": "X", "reason": "unknown"},
                ],
            },
            provider="rules",
            portfolio_symbols=["AMZN", "GOOG"],
        )
        self.assertEqual(
            result["relevantSymbols"],
            [{"symbol": "GOOG", "reason": "Ads leverage"}],
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
    with psycopg.connect(get_database_url(), autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    reset_bootstrap_user_cache()
    init_db()


@unittest.skipUnless(DB_AVAILABLE, "TEST_DATABASE_URL not set or unreachable")
class NoteLinksServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        _reset_schema()
        os.environ["NOTE_AUTOSYNTH"] = "0"
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO users (email, name) VALUES (%s, %s) RETURNING id",
                ("notes-links@example.com", "Notes Links"),
            )
            row = conn.execute(
                "SELECT id FROM users WHERE email = %s",
                ("notes-links@example.com",),
            ).fetchone()
            self.user_id = int(row["id"])
            conn.execute(
                "INSERT INTO symbols (user_id, symbol) VALUES (%s, %s), (%s, %s), (%s, %s)",
                (self.user_id, "AMZN", self.user_id, "GOOG", self.user_id, "AAPL"),
            )
            conn.commit()
        set_current_user_id(self.user_id)
        self.notes = NotesService()

    def tearDown(self) -> None:
        set_current_user_id(None)

    def test_add_note_provisional_link_and_list_from_home(self):
        note = self.notes.add_note("AMZN", {"text": "Amazon cloud commentary", "date": "2026-01-01"})
        self.assertEqual(note["symbol"], "AMZN")
        self.assertEqual(note["symbols"], ["AMZN"])
        listed = self.notes.list_notes("AMZN")
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["id"], note["id"])

    def test_update_symbols_enforces_min_one_and_lists_on_second(self):
        note = self.notes.add_note("AMZN", {"text": "Shared AI note", "date": "2026-01-02"})
        updated = self.notes.update_note(
            "AMZN", note["id"], {"symbols": ["AMZN", "GOOG"], "text": note["text"]}
        )
        self.assertEqual(updated["symbols"], ["AMZN", "GOOG"])
        self.assertEqual(len(self.notes.list_notes("GOOG")), 1)
        with self.assertRaises(ValueError):
            self.notes.update_note("AMZN", note["id"], {"symbols": []})

    def test_synth_merge_adds_links_only(self):
        note = self.notes.add_note("AMZN", {"text": "Cloud and ads", "date": "2026-01-03"})
        fake = {
            "summary": "ok",
            "growthTrajectory": [],
            "revenueProjections": [],
            "catalystsToWatch": [],
            "sentiment": "neutral",
            "relevantSymbols": [
                {"symbol": "GOOG", "reason": "Ads"},
                {"symbol": "AAPL", "reason": "Device AI"},
            ],
            "provider": "rules",
        }
        with patch.object(self.notes.llm_client, "synthesize_note", return_value=dict(fake)):
            out = self.notes.synthesize_note("AMZN", note["id"], force=True, manual=False)
        self.assertIn("GOOG", out["symbols"])
        self.assertIn("AAPL", out["symbols"])
        self.assertIn("AMZN", out["symbols"])
        # Re-synth with fewer relevant symbols must not remove GOOG/AAPL.
        fake2 = {
            **fake,
            "relevantSymbols": [{"symbol": "GOOG", "reason": "Ads still"}],
        }
        with patch.object(self.notes.llm_client, "synthesize_note", return_value=dict(fake2)):
            out2 = self.notes.synthesize_note("AMZN", note["id"], force=True, manual=False)
        self.assertEqual(sorted(out2["symbols"]), ["AAPL", "AMZN", "GOOG"])

    def test_find_by_content_and_ensure_links(self):
        note = self.notes.add_note(
            "AMZN",
            {"text": "Unique body", "date": "2026-02-01", "source": "news"},
        )
        found = self.notes.find_note_by_content("2026-02-01", "news", "Unique body")
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found["id"], note["id"])
        linked = self.notes.ensure_links(note["id"], ["GOOG", "AAPL"])
        self.assertEqual(sorted(linked["symbols"]), ["AAPL", "AMZN", "GOOG"])
        self.assertEqual(len(self.notes.list_notes("GOOG")), 1)


if __name__ == "__main__":
    unittest.main()
