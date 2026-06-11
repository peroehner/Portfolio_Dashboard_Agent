import json
import os
import time
from typing import Any

from db.database import get_connection
from services.llm_client import LLMClient


class NotesService:
    NOTE_COLUMNS = (
        "id, symbol, note_date, source, text, synthesis, synthesis_provider, synthesized_at, created_at"
    )

    def __init__(self):
        self.llm_client = LLMClient()

    def list_notes(self, symbol: str) -> list[dict[str, Any]]:
        symbol = symbol.upper()
        with get_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT {self.NOTE_COLUMNS}
                FROM notes
                WHERE symbol = ?
                ORDER BY note_date DESC, created_at DESC
                """,
                (symbol,),
            ).fetchall()
        return [self._row_to_note(row) for row in rows]

    def get_note(self, symbol: str, note_id: int) -> dict[str, Any] | None:
        symbol = symbol.upper()
        with get_connection() as conn:
            row = conn.execute(
                f"SELECT {self.NOTE_COLUMNS} FROM notes WHERE id = ? AND symbol = ?",
                (note_id, symbol),
            ).fetchone()
        return self._row_to_note(row) if row else None

    def add_note(self, symbol: str, data: dict[str, Any]) -> dict[str, Any]:
        symbol = symbol.upper()
        self._ensure_symbol_exists(symbol)

        text = (data.get("text") or "").strip()
        if not text:
            raise ValueError("Note text is required.")

        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO notes (symbol, note_date, source, text)
                VALUES (?, ?, ?, ?)
                """,
                (
                    symbol,
                    data.get("date") or data.get("note_date"),
                    data.get("source"),
                    text,
                ),
            )
            conn.commit()
            note_id = cursor.lastrowid

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

        with get_connection() as conn:
            if content_changed:
                conn.execute(
                    """
                    UPDATE notes
                    SET note_date = ?, source = ?, text = ?,
                        synthesis = NULL, synthesis_provider = NULL, synthesized_at = NULL
                    WHERE id = ? AND symbol = ?
                    """,
                    (note_date, source, text, note_id, symbol),
                )
            else:
                conn.execute(
                    """
                    UPDATE notes
                    SET note_date = ?, source = ?, text = ?
                    WHERE id = ? AND symbol = ?
                    """,
                    (note_date, source, text, note_id, symbol),
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

        with get_connection() as conn:
            conn.execute(
                """
                UPDATE notes
                SET synthesis = ?, synthesis_provider = ?, synthesized_at = datetime('now')
                WHERE id = ? AND symbol = ?
                """,
                (synthesis_json, provider, note_id, symbol),
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

    def delete_note(self, symbol: str, note_id: int) -> bool:
        symbol = symbol.upper()
        with get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM notes WHERE id = ? AND symbol = ?",
                (note_id, symbol),
            )
            conn.commit()
            return cursor.rowcount > 0

    def _ensure_symbol_exists(self, symbol: str) -> None:
        with get_connection() as conn:
            existing = conn.execute(
                "SELECT symbol FROM symbols WHERE symbol = ?",
                (symbol,),
            ).fetchone()
            if existing is None:
                conn.execute("INSERT INTO symbols (symbol) VALUES (?)", (symbol,))
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
