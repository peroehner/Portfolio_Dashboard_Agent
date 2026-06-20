"""Postgres data layer (psycopg3 + connection pool).

The whole app talks to Postgres. Locally use the bundled docker-compose service
(`docker compose up -d db`); on Render a managed Postgres provides `DATABASE_URL`.

Connections are handed out from a pool and used as context managers, mirroring
the previous SQLite usage:

    with get_connection() as conn:
        conn.execute("SELECT ...", (param,)).fetchone()
        conn.commit()

On block exit the transaction is committed (or rolled back on error) and the
connection is returned to the pool. Rows are returned as dicts (`dict_row`).
"""

import atexit
import os

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/portfolio"

# created_at/updated_at are stored as plain text ('YYYY-MM-DD HH:MM:SS', UTC) to
# keep the exact wire format the frontend already renders. app_now_text() is the
# Postgres equivalent of SQLite's datetime('now').
NOW_TEXT = "app_now_text()"

SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE OR REPLACE FUNCTION app_now_text() RETURNS text
    LANGUAGE sql STABLE AS $$
        SELECT to_char(timezone('UTC', now()), 'YYYY-MM-DD HH24:MI:SS')
    $$
    """,
    """
    CREATE TABLE IF NOT EXISTS symbols (
        symbol TEXT PRIMARY KEY,
        current_price DOUBLE PRECISION,
        target_price DOUBLE PRECISION,
        buy_below DOUBLE PRECISION,
        sell_above DOUBLE PRECISION,
        annual_dividend DOUBLE PRECISION,
        analyst_target_1y DOUBLE PRECISION,
        day_change_pct DOUBLE PRECISION,
        created_at TEXT NOT NULL DEFAULT app_now_text(),
        updated_at TEXT NOT NULL DEFAULT app_now_text()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS notes (
        id BIGSERIAL PRIMARY KEY,
        symbol TEXT NOT NULL REFERENCES symbols(symbol) ON DELETE CASCADE,
        note_date TEXT,
        source TEXT,
        text TEXT NOT NULL,
        synthesis TEXT,
        synthesis_provider TEXT,
        synthesized_at TEXT,
        created_at TEXT NOT NULL DEFAULT app_now_text()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_notes_symbol ON notes(symbol)",
    """
    CREATE TABLE IF NOT EXISTS alerts (
        id BIGSERIAL PRIMARY KEY,
        symbol TEXT NOT NULL REFERENCES symbols(symbol) ON DELETE CASCADE,
        alert_type TEXT NOT NULL,
        message TEXT NOT NULL,
        price DOUBLE PRECISION,
        reference_value DOUBLE PRECISION,
        fib_level TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL DEFAULT app_now_text()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_alerts_symbol ON alerts(symbol)",
    "CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status)",
    """
    CREATE TABLE IF NOT EXISTS assessments (
        id BIGSERIAL PRIMARY KEY,
        symbol TEXT NOT NULL REFERENCES symbols(symbol) ON DELETE CASCADE,
        action TEXT NOT NULL,
        confidence TEXT NOT NULL,
        rationale TEXT NOT NULL,
        factors TEXT,
        note_synthesis TEXT,
        trading_recommendation TEXT,
        provider TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT app_now_text()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_assessments_symbol ON assessments(symbol)",
    """
    CREATE TABLE IF NOT EXISTS holdings (
        symbol TEXT PRIMARY KEY REFERENCES symbols(symbol) ON DELETE CASCADE,
        quantity DOUBLE PRECISION NOT NULL DEFAULT 0,
        cost_basis DOUBLE PRECISION,
        purchase_date TEXT,
        account_name TEXT,
        created_at TEXT NOT NULL DEFAULT app_now_text(),
        updated_at TEXT NOT NULL DEFAULT app_now_text()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS symbol_technical (
        symbol TEXT PRIMARY KEY REFERENCES symbols(symbol) ON DELETE CASCADE,
        window_start TEXT,
        window_end TEXT,
        fib_anchor TEXT,
        trends_json TEXT NOT NULL DEFAULT '[]',
        fib_levels_json TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT NOT NULL DEFAULT app_now_text()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS recommendation_changelog (
        id BIGSERIAL PRIMARY KEY,
        symbol TEXT NOT NULL REFERENCES symbols(symbol) ON DELETE CASCADE,
        old_action TEXT,
        new_action TEXT NOT NULL,
        old_confidence TEXT,
        new_confidence TEXT,
        provider TEXT,
        created_at TEXT NOT NULL DEFAULT app_now_text()
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_reco_changelog_symbol ON recommendation_changelog(symbol)",
    "CREATE INDEX IF NOT EXISTS idx_reco_changelog_created ON recommendation_changelog(created_at)",
    """
    CREATE TABLE IF NOT EXISTS app_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
)

# Idempotent column adds so an already-deployed Postgres picks up new columns
# without a manual migration. Safe to run on every boot.
MIGRATION_STATEMENTS: tuple[str, ...] = (
    "ALTER TABLE symbols ADD COLUMN IF NOT EXISTS annual_dividend DOUBLE PRECISION",
    "ALTER TABLE symbols ADD COLUMN IF NOT EXISTS analyst_target_1y DOUBLE PRECISION",
    "ALTER TABLE symbols ADD COLUMN IF NOT EXISTS day_change_pct DOUBLE PRECISION",
    "ALTER TABLE assessments ADD COLUMN IF NOT EXISTS note_synthesis TEXT",
    "ALTER TABLE assessments ADD COLUMN IF NOT EXISTS trading_recommendation TEXT",
    "ALTER TABLE notes ADD COLUMN IF NOT EXISTS synthesis TEXT",
    "ALTER TABLE notes ADD COLUMN IF NOT EXISTS synthesis_provider TEXT",
    "ALTER TABLE notes ADD COLUMN IF NOT EXISTS synthesized_at TEXT",
    "ALTER TABLE holdings ADD COLUMN IF NOT EXISTS purchase_date TEXT",
)

_pool: ConnectionPool | None = None


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)
    # Render/Heroku style "postgres://" is accepted by libpq, but normalize for
    # consistency with tooling that only knows "postgresql://".
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    return url


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        pool = ConnectionPool(
            conninfo=get_database_url(),
            min_size=int(os.environ.get("DB_POOL_MIN", "1")),
            max_size=int(os.environ.get("DB_POOL_MAX", "10")),
            max_idle=float(os.environ.get("DB_POOL_MAX_IDLE", "60")),
            kwargs={"row_factory": dict_row},
            open=False,
        )
        pool.open()
        _pool = pool
    return _pool


def get_connection():
    """Return a pooled connection context manager.

    Usage: ``with get_connection() as conn: ...`` — commits on success and
    returns the connection to the pool on exit.
    """
    return _get_pool().connection()


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


atexit.register(close_pool)


def _run_data_migrations(conn: psycopg.Connection) -> None:
    conn.execute(
        """
        INSERT INTO app_meta (key, value)
        VALUES ('schema_initialized', app_now_text())
        ON CONFLICT (key) DO NOTHING
        """
    )
    row = conn.execute(
        "SELECT 1 FROM app_meta WHERE key = %s",
        ("assessment_max3_cleanup_v1",),
    ).fetchone()
    if row is not None:
        return
    conn.execute(
        """
        DELETE FROM assessments
        WHERE id IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY symbol ORDER BY created_at DESC, id DESC
                       ) AS rn
                FROM assessments
            ) ranked
            WHERE rn > 3
        )
        """
    )
    conn.execute(
        "INSERT INTO app_meta (key, value) VALUES (%s, app_now_text()) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
        ("assessment_max3_cleanup_v1",),
    )


def init_db() -> None:
    with get_connection() as conn:
        for statement in SCHEMA_STATEMENTS:
            conn.execute(statement)
        for statement in MIGRATION_STATEMENTS:
            conn.execute(statement)
        _run_data_migrations(conn)
        conn.commit()
