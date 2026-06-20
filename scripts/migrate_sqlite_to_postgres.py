"""One-time migration: copy an existing SQLite portfolio DB into Postgres.

Usage:
    # point at your Postgres (or rely on DATABASE_URL / .env default)
    export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/portfolio
    python scripts/migrate_sqlite_to_postgres.py [path/to/portfolio.db]

If no path is given it uses $DATABASE_PATH, then data/portfolio.db. The script is
idempotent: rows that already exist (by primary key) are skipped, so it is safe
to re-run. Identity sequences are advanced past the imported ids at the end.
"""

import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg

from db.database import get_database_url, init_db

# Target table -> ordered columns we know about in Postgres. Only columns that
# also exist in the source SQLite table are copied.
TABLES: dict[str, list[str]] = {
    "symbols": [
        "symbol", "current_price", "target_price", "buy_below", "sell_above",
        "annual_dividend", "analyst_target_1y", "day_change_pct",
        "created_at", "updated_at",
    ],
    "holdings": [
        "symbol", "quantity", "cost_basis", "purchase_date", "account_name",
        "created_at", "updated_at",
    ],
    "notes": [
        "id", "symbol", "note_date", "source", "text", "synthesis",
        "synthesis_provider", "synthesized_at", "created_at",
    ],
    "alerts": [
        "id", "symbol", "alert_type", "message", "price", "reference_value",
        "fib_level", "status", "created_at",
    ],
    "assessments": [
        "id", "symbol", "action", "confidence", "rationale", "factors",
        "note_synthesis", "trading_recommendation", "provider", "created_at",
    ],
    "symbol_technical": [
        "symbol", "window_start", "window_end", "fib_anchor",
        "trends_json", "fib_levels_json", "updated_at",
    ],
    "recommendation_changelog": [
        "id", "symbol", "old_action", "new_action", "old_confidence",
        "new_confidence", "provider", "created_at",
    ],
    "app_meta": ["key", "value"],
}

# Tables whose primary key is a serial id and whose sequence must be bumped.
SERIAL_TABLES = ["notes", "alerts", "assessments", "recommendation_changelog"]

PK = {
    "symbols": "symbol",
    "holdings": "symbol",
    "symbol_technical": "symbol",
    "app_meta": "key",
    "notes": "id",
    "alerts": "id",
    "assessments": "id",
    "recommendation_changelog": "id",
}


def _sqlite_path() -> Path:
    if len(sys.argv) > 1:
        return Path(sys.argv[1])
    base = Path(__file__).resolve().parent.parent
    return Path(os.environ.get("DATABASE_PATH", base / "data" / "portfolio.db"))


def _sqlite_columns(scon: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in scon.execute(f"PRAGMA table_info({table})")}


def main() -> None:
    src = _sqlite_path()
    if not src.exists():
        print(f"SQLite DB not found at {src}; nothing to migrate.")
        return

    print(f"Source SQLite : {src}")
    print(f"Target Postgres: {get_database_url()}")

    init_db()  # ensure target schema exists

    scon = sqlite3.connect(str(src))
    scon.row_factory = sqlite3.Row
    pcon = psycopg.connect(get_database_url())

    existing_tables = {
        row[0]
        for row in scon.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }

    total = 0
    try:
        for table, target_cols in TABLES.items():
            if table not in existing_tables:
                print(f"  - {table}: not in source, skipped")
                continue
            src_cols = _sqlite_columns(scon, table)
            cols = [c for c in target_cols if c in src_cols]
            if not cols:
                continue
            rows = scon.execute(
                f"SELECT {', '.join(cols)} FROM {table}"
            ).fetchall()
            if not rows:
                print(f"  - {table}: 0 rows")
                continue
            placeholders = ", ".join(["%s"] * len(cols))
            collist = ", ".join(cols)
            sql = (
                f"INSERT INTO {table} ({collist}) VALUES ({placeholders}) "
                f"ON CONFLICT ({PK[table]}) DO NOTHING"
            )
            with pcon.cursor() as cur:
                cur.executemany(sql, [tuple(r[c] for c in cols) for r in rows])
            pcon.commit()
            print(f"  - {table}: {len(rows)} rows")
            total += len(rows)

        # Advance identity sequences past the highest imported id.
        with pcon.cursor() as cur:
            for table in SERIAL_TABLES:
                cur.execute(
                    f"SELECT setval(pg_get_serial_sequence(%s, 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM {table}), 1), "
                    f"(SELECT COUNT(*) FROM {table}) > 0)",
                    (table,),
                )
        pcon.commit()
    finally:
        scon.close()
        pcon.close()

    print(f"Done. Imported {total} rows.")


if __name__ == "__main__":
    main()
