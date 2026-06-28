import json
import logging
import os
import time
from typing import Any

from db.database import get_connection, get_current_user_id
from services.llm_client import LLMClient

# Auto-synthesize a note the moment it is saved, so personal notes actually feed
# assessments/recommendations instead of sitting unsynthesized forever. Default on;
# set NOTE_AUTOSYNTH=0 to restore the old "synthesize only on explicit request"
# behaviour. NOTE: the auto path only fires when a real LLM provider is configured
# (see add_note) — with no key we skip and leave the note unsynthesized rather than
# persist a low-value rules-extracted synthesis. Explicit synthesis (the Synthesize
# button / backfill) still uses the deterministic rules fallback as before.
NOTE_AUTOSYNTH = os.environ.get("NOTE_AUTOSYNTH", "1").lower() not in (
    "0",
    "false",
    "no",
    "off",
)


class NotesService:
    NOTE_COLUMNS = (
        "id, symbol, note_date, source, text, synthesis, synthesis_provider, synthesized_at, created_at"
    )

    def __init__(self):
        self.llm_client = LLMClient()

    def list_notes(self, symbol: str) -> list[dict[str, Any]]:
        symbol = symbol.upper()
        user_id = get_current_user_id()
        with get_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT {self.NOTE_COLUMNS}
                FROM notes
                WHERE user_id = %s AND symbol = %s
                ORDER BY note_date DESC, created_at DESC
                """,
                (user_id, symbol),
            ).fetchall()
        return [self._row_to_note(row) for row in rows]

    def get_note(self, symbol: str, note_id: int) -> dict[str, Any] | None:
        symbol = symbol.upper()
        user_id = get_current_user_id()
        with get_connection() as conn:
            row = conn.execute(
                f"SELECT {self.NOTE_COLUMNS} FROM notes "
                "WHERE id = %s AND user_id = %s AND symbol = %s",
                (note_id, user_id, symbol),
            ).fetchone()
        return self._row_to_note(row) if row else None

    def add_note(self, symbol: str, data: dict[str, Any]) -> dict[str, Any]:
        symbol = symbol.upper()
        self._ensure_symbol_exists(symbol)

        text = (data.get("text") or "").strip()
        if not text:
            raise ValueError("Note text is required.")

        user_id = get_current_user_id()
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO notes (user_id, symbol, note_date, source, text)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    user_id,
                    symbol,
                    data.get("date") or data.get("note_date"),
                    data.get("source"),
                    text,
                ),
            )
            note_id = cursor.fetchone()["id"]
            conn.commit()

        note = self.get_note(symbol, note_id)
        assert note is not None

        # Revive the notes->synthesis pipeline: synthesize on save so the note's
        # structured guidance flows into _build_context (noteSyntheses) automatically.
        # Gated on a real LLM provider so a no-key install behaves exactly like today
        # (note left unsynthesized, unsynthesizedNoteCount preserved). Synthesis must
        # never block note creation, so any failure is swallowed with a warning.
        if NOTE_AUTOSYNTH and self.llm_client.active_provider() in ("openai", "gemini"):
            try:
                note = self.synthesize_note(symbol, note_id)
            except Exception as exc:  # noqa: BLE001 - note is already saved; synthesis is best-effort
                logging.warning(
                    "Auto-synthesis failed for note %s (%s); leaving unsynthesized: %s",
                    note_id,
                    symbol,
                    exc,
                )
        return note

    def import_note(self, symbol: str, data: dict[str, Any]) -> dict[str, Any]:
        """Insert a note verbatim, preserving any pre-computed synthesis.

        Used by the importer so an Export -> Import round-trip is lossless: unlike
        add_note this never auto-synthesizes (the synthesis is restored as-is from
        the export payload), so no LLM call is made and the original synthesis is
        not lost or regenerated.
        """
        symbol = symbol.upper()
        self._ensure_symbol_exists(symbol)

        text = (data.get("text") or "").strip()
        if not text:
            raise ValueError("Note text is required.")

        synthesis = data.get("synthesis")
        if isinstance(synthesis, (dict, list)):
            synthesis_json = json.dumps(synthesis)
        elif isinstance(synthesis, str) and synthesis.strip():
            synthesis_json = synthesis
        else:
            synthesis_json = None

        user_id = get_current_user_id()
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO notes (
                    user_id, symbol, note_date, source, text,
                    synthesis, synthesis_provider, synthesized_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    user_id,
                    symbol,
                    data.get("date") or data.get("note_date"),
                    data.get("source"),
                    text,
                    synthesis_json,
                    data.get("synthesisProvider") or data.get("synthesis_provider"),
                    data.get("synthesizedAt") or data.get("synthesized_at"),
                ),
            )
            note_id = cursor.fetchone()["id"]
            conn.commit()

        note = self.get_note(symbol, note_id)
        assert note is not None
        return note

    def update_note(self, symbol: str, note_id: int, data: dict[str, Any]) -> dict[str, Any]:
        symbol = symbol.upper()
        note = self.get_note(symbol, note_id)
        if note is None:
            raise ValueError(f"Note {note_id} not found for {symbol}.")

        text = (data.get("text") or "").strip()
        if not text:
            raise ValueError("Note text is required.")

        note_date = data.get("date") or data.get("note_date")
        source = (data.get("source") or "").strip() or None
        content_changed = (
            text != note["text"]
            or (note_date or None) != (note.get("date") or None)
            or source != (note.get("source") or None)
        )

        user_id = get_current_user_id()
        with get_connection() as conn:
            if content_changed:
                conn.execute(
                    """
                    UPDATE notes
                    SET note_date = %s, source = %s, text = %s,
                        synthesis = NULL, synthesis_provider = NULL, synthesized_at = NULL
                    WHERE id = %s AND user_id = %s AND symbol = %s
                    """,
                    (note_date, source, text, note_id, user_id, symbol),
                )
            else:
                conn.execute(
                    """
                    UPDATE notes
                    SET note_date = %s, source = %s, text = %s
                    WHERE id = %s AND user_id = %s AND symbol = %s
                    """,
                    (note_date, source, text, note_id, user_id, symbol),
                )
            conn.commit()

        updated = self.get_note(symbol, note_id)
        assert updated is not None
        return updated

    def synthesize_note(
        self, symbol: str, note_id: int, force: bool = False, guidance: str | None = None
    ) -> dict[str, Any]:
        """Send raw note + prompt to LLM; persist synthesis on the note."""
        symbol = symbol.upper()
        note = self.get_note(symbol, note_id)
        if note is None:
            raise ValueError(f"Note {note_id} not found for {symbol}.")

        if note.get("synthesis") and not force:
            return note

        synthesis = self.llm_client.synthesize_note(symbol, note, guidance=guidance)
        provider = synthesis.pop("provider", self.llm_client.active_provider())
        synthesis_json = json.dumps(synthesis)

        user_id = get_current_user_id()
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE notes
                SET synthesis = %s, synthesis_provider = %s, synthesized_at = app_now_text()
                WHERE id = %s AND user_id = %s AND symbol = %s
                """,
                (synthesis_json, provider, note_id, user_id, symbol),
            )
            conn.commit()

        updated = self.get_note(symbol, note_id)
        assert updated is not None
        return updated

    def synthesize_all_notes(
        self, symbol: str, force: bool = False, guidance: str | None = None
    ) -> list[dict[str, Any]]:
        """Synthesize every note for a symbol (skips notes that already have synthesis unless force)."""
        symbol = symbol.upper()
        notes = self.list_notes(symbol)
        if not notes:
            raise ValueError(f"No notes found for {symbol}.")

        batch_delay = float(os.environ.get("NOTE_SYNTHESIS_BATCH_DELAY", "8"))
        results = []
        for index, note in enumerate(notes):
            if index > 0:
                time.sleep(batch_delay)
            if note.get("synthesis") and not force:
                results.append(note)
            else:
                results.append(self.synthesize_note(symbol, note["id"], force=force, guidance=guidance))
        return results

    def synthesize_unsynthesized_notes(
        self, force: bool = False, guidance: str | None = None
    ) -> dict[str, Any]:
        """Backfill: synthesize every note for the CURRENT user that lacks a synthesis
        (or all notes when ``force``). Reusable by the CLI backfill script / an admin
        path. Uses the same provider+fallback rules as :meth:`synthesize_note`, with a
        delay between calls to respect LLM rate limits. Returns a summary dict; never
        raises on a single-note failure (it is recorded and the loop continues)."""
        user_id = get_current_user_id()
        with get_connection() as conn:
            query = (
                "SELECT id, symbol FROM notes WHERE user_id = %s ORDER BY symbol, id"
                if force
                else "SELECT id, symbol FROM notes WHERE user_id = %s AND synthesis IS NULL "
                "ORDER BY symbol, id"
            )
            rows = conn.execute(query, (user_id,)).fetchall()

        batch_delay = float(os.environ.get("NOTE_SYNTHESIS_BATCH_DELAY", "8"))
        results: list[dict[str, Any]] = []
        providers: dict[str, int] = {}
        for index, row in enumerate(rows):
            if index > 0:
                time.sleep(batch_delay)
            try:
                note = self.synthesize_note(
                    row["symbol"], row["id"], force=force, guidance=guidance
                )
                provider = note.get("synthesisProvider") or "unknown"
                providers[provider] = providers.get(provider, 0) + 1
                results.append(
                    {"id": row["id"], "symbol": row["symbol"], "provider": provider, "ok": True}
                )
            except Exception as exc:  # noqa: BLE001 - keep backfilling the rest
                logging.warning("Backfill synthesis failed for note %s (%s): %s",
                                row["id"], row["symbol"], exc)
                results.append(
                    {"id": row["id"], "symbol": row["symbol"], "ok": False, "error": str(exc)[:200]}
                )

        return {
            "candidates": len(rows),
            "synthesized": sum(1 for r in results if r["ok"]),
            "failed": sum(1 for r in results if not r["ok"]),
            "providers": providers,
            "results": results,
        }

    def delete_note(self, symbol: str, note_id: int) -> bool:
        symbol = symbol.upper()
        user_id = get_current_user_id()
        with get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM notes WHERE id = %s AND user_id = %s AND symbol = %s",
                (note_id, user_id, symbol),
            )
            conn.commit()
            return cursor.rowcount > 0

    def _ensure_symbol_exists(self, symbol: str) -> None:
        user_id = get_current_user_id()
        with get_connection() as conn:
            existing = conn.execute(
                "SELECT symbol FROM symbols WHERE user_id = %s AND symbol = %s",
                (user_id, symbol),
            ).fetchone()
            if existing is None:
                conn.execute(
                    "INSERT INTO symbols (user_id, symbol) VALUES (%s, %s)",
                    (user_id, symbol),
                )
                conn.commit()

    def _row_to_note(self, row) -> dict[str, Any]:
        synthesis = None
        if row["synthesis"]:
            try:
                synthesis = json.loads(row["synthesis"])
            except json.JSONDecodeError:
                synthesis = {"summary": row["synthesis"]}

        return {
            "id": row["id"],
            "symbol": row["symbol"],
            "date": row["note_date"],
            "source": row["source"],
            "text": row["text"],
            "synthesis": synthesis,
            "synthesisProvider": row["synthesis_provider"],
            "synthesizedAt": row["synthesized_at"],
            "createdAt": row["created_at"],
        }
