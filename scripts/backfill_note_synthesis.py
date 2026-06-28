#!/usr/bin/env python3
"""Backfill note synthesis for a user's existing, unsynthesized notes.

Synthesis is what turns a raw personal note into the structured guidance
(`summary`, `growthTrajectory`, `catalystsToWatch`, `sentiment`, ...) that
`AssessmentService._build_context` reads as `noteSyntheses`. New notes are now
auto-synthesized on save (see NotesService.add_note), but notes created before
that wiring stay `synthesis IS NULL`; this script fills them in.

This is the ONLY mass-synthesis entry point — it is never run as a side effect of
import or app start. It mutates ONLY the `notes.synthesis` columns (no other table).

By default it requires a real LLM provider (a GEMINI/OPENAI key) so it produces
genuine syntheses; pass --allow-rules to fall back to the deterministic
regex-based synthesis when no key is set.

Usage:
    python scripts/backfill_note_synthesis.py                 # default user, dry-run preview
    python scripts/backfill_note_synthesis.py --apply         # actually synthesize
    python scripts/backfill_note_synthesis.py --email a@b.com --apply
    python scripts/backfill_note_synthesis.py --bootstrap --apply
    python scripts/backfill_note_synthesis.py --apply --force        # re-synthesize ALL notes
    python scripts/backfill_note_synthesis.py --apply --allow-rules  # no key: use rules fallback

Requires GEMINI_API_KEY or OPENAI_API_KEY to generate real (non-fallback) syntheses.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

DEFAULT_EMAIL = "peroehner@gmail.com"


def _load_env() -> None:
    env_path = BASE_DIR / ".env"
    if not env_path.is_file():
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(env_path, override=False)
    except ImportError:  # pragma: no cover - dotenv is a declared dependency
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            if value and value.lstrip()[:1] not in ("'", '"') and "#" in value:
                value = value.split("#", 1)[0]
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    _load_env()

    parser = argparse.ArgumentParser(description="Backfill note synthesis (read-only unless --apply).")
    parser.add_argument("--email", default=DEFAULT_EMAIL, help="user email to backfill")
    parser.add_argument("--bootstrap", action="store_true", help="force the bootstrap user")
    parser.add_argument("--apply", action="store_true", help="actually write syntheses (default: dry run)")
    parser.add_argument("--force", action="store_true", help="re-synthesize ALL notes, not just unsynthesized")
    parser.add_argument("--allow-rules", action="store_true", help="permit the rules fallback when no LLM key")
    args = parser.parse_args()

    from db.database import BOOTSTRAP_USER_EMAIL, get_connection, set_current_user_id
    from services.llm_client import LLMClient
    from services.notes_service import NotesService

    # Resolve user (SELECT only; never creates a user).
    def resolve_user_id() -> tuple[int | None, str]:
        emails = [BOOTSTRAP_USER_EMAIL] if args.bootstrap else [args.email, BOOTSTRAP_USER_EMAIL]
        with get_connection() as conn:
            for email in emails:
                row = conn.execute("SELECT id, email FROM users WHERE email = %s", (email,)).fetchone()
                if row:
                    return int(row["id"]), row["email"]
        return None, ""

    user_id, email = resolve_user_id()
    if user_id is None:
        print(f"ERROR: no user found for {args.email!r} or bootstrap.")
        return 1
    set_current_user_id(user_id)
    print(f"User: id={user_id} <{email}>")

    provider = LLMClient().active_provider()
    print(f"Active LLM provider: {provider}")

    # Count candidates up front.
    with get_connection() as conn:
        if args.force:
            candidates = conn.execute(
                "SELECT COUNT(*) AS n FROM notes WHERE user_id = %s", (user_id,)
            ).fetchone()["n"]
        else:
            candidates = conn.execute(
                "SELECT COUNT(*) AS n FROM notes WHERE user_id = %s AND synthesis IS NULL", (user_id,)
            ).fetchone()["n"]
    scope = "ALL notes" if args.force else "unsynthesized notes"
    print(f"Candidates ({scope}): {candidates}")

    if candidates == 0:
        print("Nothing to do.")
        return 0

    llm_ready = provider in ("openai", "gemini")
    if not llm_ready and not args.allow_rules:
        print(
            "\nNo LLM key configured (provider=rules). Real syntheses need GEMINI_API_KEY "
            "or OPENAI_API_KEY.\n"
            "  • Set a key and re-run --apply, OR\n"
            "  • pass --allow-rules to use the deterministic regex fallback.\n"
            "No notes were modified."
        )
        return 0

    if not args.apply:
        print(
            f"\nDRY RUN — would synthesize {candidates} note(s) via '{provider}'. "
            "Re-run with --apply to write."
        )
        return 0

    print(f"\nSynthesizing {candidates} note(s) via '{provider}' (this calls the LLM per note)...")
    summary = NotesService().synthesize_unsynthesized_notes(force=args.force)
    print(f"Done. candidates={summary['candidates']} synthesized={summary['synthesized']} "
          f"failed={summary['failed']} providers={summary['providers']}")
    for r in summary["results"]:
        status = "ok" if r["ok"] else f"FAILED: {r.get('error')}"
        print(f"  {r['symbol']:8} note#{r['id']}: {r.get('provider', '-')} {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
