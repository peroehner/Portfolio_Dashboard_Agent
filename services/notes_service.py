from typing import Any

from db.database import get_connection


class NotesService:
    def list_notes(self, symbol: str) -> list[dict[str, Any]]:
        symbol = symbol.upper()
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, symbol, note_date, source, text, created_at
                FROM notes
                WHERE symbol = ?
                ORDER BY note_date DESC, created_at DESC
                """,
                (symbol,),
            ).fetchall()
        return [self._row_to_note(row) for row in rows]

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
            row = conn.execute(
                "SELECT id, symbol, note_date, source, text, created_at FROM notes WHERE id = ?",
                (note_id,),
            ).fetchone()

        assert row is not None
        return self._row_to_note(row)

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
        return {
            "id": row["id"],
            "symbol": row["symbol"],
            "date": row["note_date"],
            "source": row["source"],
            "text": row["text"],
            "createdAt": row["created_at"],
        }
