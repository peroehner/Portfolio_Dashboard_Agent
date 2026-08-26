import json
import logging
import os
import re
import time
from typing import Any

from db.database import get_connection, get_current_user_id
from services.llm_client import LLMClient

_PROMPT_KEY_RE = re.compile(r"^\s*prompt\s*:\s*(.*)$")
_AT_PROMPT_RE = re.compile(r"^@prompt\s*:\s*(.*)$", re.IGNORECASE)
_BLOCK_SCALAR_INDICATORS = {"|", ">", "|-", ">-", "|+", ">+"}


def _parse_front_matter_prompt(text: str) -> str | None:
    """Extract a ``prompt:`` value from a leading ``---`` YAML front-matter block.

    Supports a single-line ``prompt: value`` and a ``prompt: |`` (or ``>``) block
    scalar. Returns None if there is no well-formed front matter (e.g. missing
    closing ``---``) or no ``prompt`` key — callers then fall back to ``@prompt:``.
    Intentionally lenient: malformed front matter is treated as a plain note.
    """
    lines = text.splitlines()
    idx = 0
    while idx < len(lines) and lines[idx].strip() == "":
        idx += 1
    if idx >= len(lines) or lines[idx].strip() != "---":
        return None

    close = None
    for j in range(idx + 1, len(lines)):
        if lines[j].strip() == "---":
            close = j
            break
    if close is None:
        return None  # malformed: no closing fence -> no directive

    block = lines[idx + 1 : close]
    for i, line in enumerate(block):
        match = _PROMPT_KEY_RE.match(line)
        if not match:
            continue
        rest = match.group(1).strip()
        if rest in _BLOCK_SCALAR_INDICATORS:
            key_indent = len(line) - len(line.lstrip())
            collected: list[str] = []
            for follow in block[i + 1 :]:
                if follow.strip() == "":
                    collected.append("")
                    continue
                follow_indent = len(follow) - len(follow.lstrip())
                if follow_indent <= key_indent:
                    break  # dedent -> next key, end of the block scalar
                collected.append(follow.strip())
            return "\n".join(collected).strip() or None
        if len(rest) >= 2 and rest[0] == rest[-1] and rest[0] in ("'", '"'):
            rest = rest[1:-1].strip()
        return rest or None
    return None


def _parse_at_prompt(text: str) -> str | None:
    """Extract a directive from a first non-empty line beginning with ``@prompt:``."""
    for line in text.splitlines():
        if line.strip() == "":
            continue
        match = _AT_PROMPT_RE.match(line.strip())
        if match:
            return match.group(1).strip() or None
        return None  # first real line isn't @prompt -> no directive
    return None


def extract_synthesis_directive(text: str | None) -> str | None:
    """Return an optional per-note synthesis directive embedded in the note body.

    Precedence: a ``prompt:`` key in leading YAML front matter wins; otherwise a
    first-line ``@prompt:`` directive; otherwise None. The directive is NOT
    stripped from the body — it stays saved/displayed and is only surfaced to
    steer the LLM. Robust to malformed input (returns None rather than raising).
    """
    if not text:
        return None
    return _parse_front_matter_prompt(text) or _parse_at_prompt(text)


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
        "notes.id, notes.user_id, notes.symbol, notes.note_date, notes.source, notes.text, "
        "notes.synthesis, notes.synthesis_provider, notes.synthesized_at, notes.created_at"
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
                INNER JOIN note_links
                  ON note_links.note_id = notes.id
                 AND note_links.user_id = notes.user_id
                WHERE note_links.user_id = %s AND note_links.symbol = %s
                ORDER BY notes.note_date DESC, notes.created_at DESC
                """,
                (user_id, symbol),
            ).fetchall()
            links_by_id = self._links_for_notes(conn, user_id, [row["id"] for row in rows])
        return [self._row_to_note(row, links_by_id.get(row["id"], [row["symbol"]])) for row in rows]

    def get_note(self, symbol: str, note_id: int) -> dict[str, Any] | None:
        symbol = symbol.upper()
        user_id = get_current_user_id()
        with get_connection() as conn:
            row = conn.execute(
                f"SELECT {self.NOTE_COLUMNS} FROM notes WHERE id = %s AND user_id = %s",
                (note_id, user_id),
            ).fetchone()
            if row is None:
                return None
            links = self._links_for_notes(conn, user_id, [note_id]).get(note_id, [])
            if not links:
                links = [row["symbol"]]
            if symbol not in links and row["symbol"].upper() != symbol:
                return None
        return self._row_to_note(row, links)

    def find_note_by_content(
        self, date: str | None, source: str | None, text: str
    ) -> dict[str, Any] | None:
        """Find a user note by (date, source, text) regardless of linked symbol."""
        text = (text or "").strip()
        if not text:
            return None
        user_id = get_current_user_id()
        with get_connection() as conn:
            row = conn.execute(
                f"""
                SELECT {self.NOTE_COLUMNS}
                FROM notes
                WHERE user_id = %s
                  AND COALESCE(note_date, '') = COALESCE(%s, '')
                  AND COALESCE(source, '') = COALESCE(%s, '')
                  AND text = %s
                ORDER BY id
                LIMIT 1
                """,
                (user_id, date, source, text),
            ).fetchone()
            if row is None:
                return None
            links = self._links_for_notes(conn, user_id, [row["id"]]).get(row["id"], [row["symbol"]])
        return self._row_to_note(row, links)

    def add_note(self, symbol: str, data: dict[str, Any]) -> dict[str, Any]:
        symbol = symbol.upper()
        self._ensure_symbol_exists(symbol)

        text = (data.get("text") or "").strip()
        if not text:
            raise ValueError("Note text is required.")

        extra = self._normalize_symbol_list(data.get("symbols"), require_nonempty=False)
        provisional_links = self._unique_symbols([symbol, *extra])

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
            self._insert_links(conn, user_id, note_id, provisional_links)
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
                note = self.synthesize_note(symbol, note_id, manual=False)
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

        extra = self._normalize_symbol_list(data.get("symbols"), require_nonempty=False)
        links = self._unique_symbols([symbol, *extra])

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
            self._insert_links(conn, user_id, note_id, links)
            conn.commit()

        note = self.get_note(symbol, note_id)
        assert note is not None
        return note

    def ensure_links(self, note_id: int, symbols: list[str]) -> dict[str, Any]:
        """Add portfolio links to an existing note (never removes). Returns updated note."""
        user_id = get_current_user_id()
        with get_connection() as conn:
            row = conn.execute(
                f"SELECT {self.NOTE_COLUMNS} FROM notes WHERE id = %s AND user_id = %s",
                (note_id, user_id),
            ).fetchone()
            if row is None:
                raise ValueError(f"Note {note_id} not found.")
            wanted = self._normalize_symbol_list(symbols, require_nonempty=False)
            for sym in wanted:
                self._ensure_symbol_exists(sym)
            self._insert_links(conn, user_id, note_id, wanted)
            conn.commit()
            links = self._links_for_notes(conn, user_id, [note_id]).get(note_id, [row["symbol"]])
        return self._row_to_note(row, links)

    def update_note(self, symbol: str, note_id: int, data: dict[str, Any]) -> dict[str, Any]:
        symbol = symbol.upper()
        note = self.get_note(symbol, note_id)
        if note is None:
            raise ValueError(f"Note {note_id} not found for {symbol}.")

        has_symbols = "symbols" in data
        has_content = any(key in data for key in ("text", "date", "note_date", "source"))

        if has_symbols:
            new_links = self._normalize_symbol_list(data.get("symbols"), require_nonempty=True)
            for sym in new_links:
                self._ensure_symbol_exists(sym)

        user_id = get_current_user_id()
        with get_connection() as conn:
            if has_content:
                text = (data.get("text") if "text" in data else note["text"]) or ""
                text = str(text).strip()
                if not text:
                    raise ValueError("Note text is required.")
                note_date = (
                    data.get("date")
                    if "date" in data or "note_date" in data
                    else note.get("date")
                )
                if "note_date" in data and "date" not in data:
                    note_date = data.get("note_date")
                source = note.get("source")
                if "source" in data:
                    source = (data.get("source") or "").strip() or None
                content_changed = (
                    text != note["text"]
                    or (note_date or None) != (note.get("date") or None)
                    or source != (note.get("source") or None)
                )
                if content_changed:
                    conn.execute(
                        """
                        UPDATE notes
                        SET note_date = %s, source = %s, text = %s,
                            synthesis = NULL, synthesis_provider = NULL, synthesized_at = NULL
                        WHERE id = %s AND user_id = %s
                        """,
                        (note_date, source, text, note_id, user_id),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE notes
                        SET note_date = %s, source = %s, text = %s
                        WHERE id = %s AND user_id = %s
                        """,
                        (note_date, source, text, note_id, user_id),
                    )

            if has_symbols:
                self._replace_links(conn, user_id, note_id, new_links)
                # Keep provisional home in sync when possible.
                home = note.get("symbol") or symbol
                if home not in new_links:
                    home = new_links[0]
                conn.execute(
                    "UPDATE notes SET symbol = %s WHERE id = %s AND user_id = %s",
                    (home, note_id, user_id),
                )

            conn.commit()

        # Re-fetch via any remaining link (viewer symbol may have been unlinked).
        with get_connection() as conn:
            row = conn.execute(
                f"SELECT {self.NOTE_COLUMNS} FROM notes WHERE id = %s AND user_id = %s",
                (note_id, user_id),
            ).fetchone()
            assert row is not None
            links = self._links_for_notes(conn, user_id, [note_id]).get(note_id, [row["symbol"]])
        return self._row_to_note(row, links)

    def synthesize_note(
        self,
        symbol: str,
        note_id: int,
        force: bool = False,
        guidance: str | None = None,
        manual: bool = True,
    ) -> dict[str, Any]:
        """Send raw note + prompt to LLM; persist synthesis on the note."""
        symbol = symbol.upper()
        note = self.get_note(symbol, note_id)
        if note is None:
            raise ValueError(f"Note {note_id} not found for {symbol}.")

        if note.get("synthesis") and not force:
            return note

        from services.plan_service import ensure_can_manual_ai_action, record_manual_ai_action

        if manual:
            ensure_can_manual_ai_action()

        # An optional directive embedded in the note body (front matter `prompt:`
        # or a leading `@prompt:` line) steers synthesis for THIS note and takes
        # precedence over any caller-supplied guidance. All call sites (auto-synth
        # in add_note, synthesize_all_notes, the backfill) funnel through here, so
        # they honor the per-note directive without each having to parse it.
        directive = extract_synthesis_directive(note.get("text"))
        portfolio = self._list_portfolio_symbols()
        synthesis = self.llm_client.synthesize_note(
            symbol,
            note,
            guidance=directive or guidance,
            portfolio_symbols=portfolio,
        )
        provider = synthesis.pop("provider", self.llm_client.active_provider())
        relevant = synthesis.get("relevantSymbols") or []
        synthesis_json = json.dumps(synthesis)

        user_id = get_current_user_id()
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE notes
                SET synthesis = %s, synthesis_provider = %s, synthesized_at = app_now_text()
                WHERE id = %s AND user_id = %s
                """,
                (synthesis_json, provider, note_id, user_id),
            )
            # Auto-add only — never remove manual links on re-synthesize.
            add_syms = [
                str(item.get("symbol") or "").upper()
                for item in relevant
                if isinstance(item, dict) and item.get("symbol")
            ]
            if add_syms:
                self._insert_links(conn, user_id, note_id, add_syms)
            conn.commit()

        if manual:
            record_manual_ai_action()

        updated = self.get_note(symbol, note_id)
        if updated is None:
            # Viewer symbol still linked in normal cases; fall back via ownership.
            with get_connection() as conn:
                row = conn.execute(
                    f"SELECT {self.NOTE_COLUMNS} FROM notes WHERE id = %s AND user_id = %s",
                    (note_id, user_id),
                ).fetchone()
                assert row is not None
                links = self._links_for_notes(conn, user_id, [note_id]).get(
                    note_id, [row["symbol"]]
                )
            return self._row_to_note(row, links)
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
                    row["symbol"], row["id"], force=force, guidance=guidance, manual=False
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
        note = self.get_note(symbol, note_id)
        if note is None:
            return False
        user_id = get_current_user_id()
        with get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM notes WHERE id = %s AND user_id = %s",
                (note_id, user_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def reassign_provisional_before_symbol_delete(self, symbol: str) -> None:
        """Before cascading symbol delete, move notes.symbol when other links remain.

        ``notes.symbol`` still FK-cascades on symbol delete. Multi-linked notes must
        point provisional home at a surviving link so the note row is kept.
        """
        symbol = symbol.upper()
        user_id = get_current_user_id()
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT n.id
                FROM notes n
                WHERE n.user_id = %s AND n.symbol = %s
                """,
                (user_id, symbol),
            ).fetchall()
            for row in rows:
                note_id = row["id"]
                other = conn.execute(
                    """
                    SELECT symbol FROM note_links
                    WHERE note_id = %s AND user_id = %s AND symbol <> %s
                    ORDER BY symbol
                    LIMIT 1
                    """,
                    (note_id, user_id, symbol),
                ).fetchone()
                if other:
                    conn.execute(
                        "UPDATE notes SET symbol = %s WHERE id = %s AND user_id = %s",
                        (other["symbol"], note_id, user_id),
                    )
            conn.commit()

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

    def _list_portfolio_symbols(self) -> list[str]:
        user_id = get_current_user_id()
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT symbol FROM symbols WHERE user_id = %s ORDER BY symbol",
                (user_id,),
            ).fetchall()
        return [row["symbol"] for row in rows]

    @staticmethod
    def _unique_symbols(symbols: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for sym in symbols:
            text = str(sym or "").strip().upper()
            if not text or text in seen:
                continue
            seen.add(text)
            out.append(text)
        return out

    def _normalize_symbol_list(
        self, raw: Any, *, require_nonempty: bool
    ) -> list[str]:
        if raw is None:
            symbols: list[str] = []
        elif isinstance(raw, str):
            symbols = self._unique_symbols([raw])
        elif isinstance(raw, (list, tuple, set)):
            symbols = self._unique_symbols([str(item) for item in raw])
        else:
            raise ValueError("symbols must be an array of tickers.")
        if require_nonempty and not symbols:
            raise ValueError("A note must stay linked to at least one symbol.")
        portfolio = set(self._list_portfolio_symbols())
        # Allow creating links only to existing portfolio symbols (ensure may add).
        if portfolio:
            unknown = [s for s in symbols if s not in portfolio]
            # Unknown tickers are created via _ensure_symbol_exists by callers when needed.
            _ = unknown
        return symbols

    @staticmethod
    def _insert_links(conn, user_id: int, note_id: int, symbols: list[str]) -> None:
        for sym in symbols:
            conn.execute(
                """
                INSERT INTO note_links (note_id, user_id, symbol)
                VALUES (%s, %s, %s)
                ON CONFLICT (note_id, symbol) DO NOTHING
                """,
                (note_id, user_id, sym),
            )

    @staticmethod
    def _replace_links(conn, user_id: int, note_id: int, symbols: list[str]) -> None:
        conn.execute(
            "DELETE FROM note_links WHERE note_id = %s AND user_id = %s",
            (note_id, user_id),
        )
        for sym in symbols:
            conn.execute(
                """
                INSERT INTO note_links (note_id, user_id, symbol)
                VALUES (%s, %s, %s)
                ON CONFLICT (note_id, symbol) DO NOTHING
                """,
                (note_id, user_id, sym),
            )

    @staticmethod
    def _links_for_notes(conn, user_id: int, note_ids: list[int]) -> dict[int, list[str]]:
        if not note_ids:
            return {}
        rows = conn.execute(
            """
            SELECT note_id, symbol
            FROM note_links
            WHERE user_id = %s AND note_id = ANY(%s)
            ORDER BY symbol
            """,
            (user_id, list(note_ids)),
        ).fetchall()
        out: dict[int, list[str]] = {}
        for row in rows:
            out.setdefault(row["note_id"], []).append(row["symbol"])
        return out

    def _row_to_note(self, row, symbols: list[str] | None = None) -> dict[str, Any]:
        synthesis = None
        if row["synthesis"]:
            try:
                synthesis = json.loads(row["synthesis"])
            except json.JSONDecodeError:
                synthesis = {"summary": row["synthesis"]}

        linked = self._unique_symbols(list(symbols or [row["symbol"]]))
        if not linked:
            linked = [row["symbol"]]

        return {
            "id": row["id"],
            "symbol": row["symbol"],
            "symbols": linked,
            "date": row["note_date"],
            "source": row["source"],
            "text": row["text"],
            "synthesis": synthesis,
            "synthesisProvider": row["synthesis_provider"],
            "synthesizedAt": row["synthesized_at"],
            "createdAt": row["created_at"],
        }
