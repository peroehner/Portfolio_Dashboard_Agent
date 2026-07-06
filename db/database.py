"""Postgres data layer (psycopg3 + connection pool) with per-user scoping.

The whole app talks to Postgres. Locally use the bundled docker-compose service
(`docker compose up -d db`) or Postgres.app; on Render a managed Postgres
provides `DATABASE_URL`.

Connections are handed out from a pool and used as context managers:

    with get_connection() as conn:
        conn.execute("SELECT ...", (param,)).fetchone()
        conn.commit()

On block exit the transaction is committed (or rolled back on error) and the
connection is returned to the pool. Rows are returned as dicts (`dict_row`).

Multi-user model
----------------
Every per-user table carries a ``user_id`` and is keyed/filtered by it. The
"current user" for a request is held in a context variable (``current_user_id``)
set by the web layer per request; services read it via ``get_current_user_id()``.
Outside a request (scripts, background jobs, tests) it falls back to a single
bootstrap user so the app keeps working as a single-user install until Google
OAuth lands in Phase 2.
"""

import atexit
import contextvars
import os

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/portfolio"

# created_at/updated_at are stored as plain text ('YYYY-MM-DD HH:MM:SS', UTC) to
# keep the exact wire format the frontend already renders. app_now_text() is the
# Postgres equivalent of SQLite's datetime('now').
NOW_TEXT = "app_now_text()"

# Per-user tables that carry a user_id and are scoped by it.
PER_USER_TABLES: tuple[str, ...] = (
    "symbols",
    "notes",
    "alerts",
    "assessments",
    "holdings",
    "symbol_technical",
    "recommendation_changelog",
)
# Child tables whose (user_id, symbol) references symbols(user_id, symbol).
CHILD_TABLES: tuple[str, ...] = (
    "notes",
    "alerts",
    "assessments",
    "holdings",
    "symbol_technical",
    "recommendation_changelog",
)

SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE OR REPLACE FUNCTION app_now_text() RETURNS text
    LANGUAGE sql STABLE AS $$
        SELECT to_char(timezone('UTC', now()), 'YYYY-MM-DD HH24:MI:SS')
    $$
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
        id BIGSERIAL PRIMARY KEY,
        google_sub TEXT UNIQUE,
        email TEXT UNIQUE NOT NULL,
        name TEXT,
        picture TEXT,
        prefer_computed_trends BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TEXT NOT NULL DEFAULT app_now_text(),
        last_login_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS symbols (
        user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        symbol TEXT NOT NULL,
        target_price DOUBLE PRECISION,
        buy_below DOUBLE PRECISION,
        sell_above DOUBLE PRECISION,
        trade_below_price DOUBLE PRECISION,
        trade_below_shares DOUBLE PRECISION,
        trade_above_price DOUBLE PRECISION,
        trade_above_shares DOUBLE PRECISION,
        annual_dividend DOUBLE PRECISION,
        created_at TEXT NOT NULL DEFAULT app_now_text(),
        updated_at TEXT NOT NULL DEFAULT app_now_text(),
        PRIMARY KEY (user_id, symbol)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS notes (
        id BIGSERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        symbol TEXT NOT NULL,
        note_date TEXT,
        source TEXT,
        text TEXT NOT NULL,
        synthesis TEXT,
        synthesis_provider TEXT,
        synthesized_at TEXT,
        created_at TEXT NOT NULL DEFAULT app_now_text(),
        FOREIGN KEY (user_id, symbol) REFERENCES symbols(user_id, symbol) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS alerts (
        id BIGSERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        symbol TEXT NOT NULL,
        alert_type TEXT NOT NULL,
        message TEXT NOT NULL,
        price DOUBLE PRECISION,
        reference_value DOUBLE PRECISION,
        fib_level TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        created_at TEXT NOT NULL DEFAULT app_now_text(),
        FOREIGN KEY (user_id, symbol) REFERENCES symbols(user_id, symbol) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS assessments (
        id BIGSERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        symbol TEXT NOT NULL,
        action TEXT NOT NULL,
        confidence TEXT NOT NULL,
        rationale TEXT NOT NULL,
        factors TEXT,
        note_synthesis TEXT,
        trading_recommendation TEXT,
        provider TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT app_now_text(),
        FOREIGN KEY (user_id, symbol) REFERENCES symbols(user_id, symbol) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS holdings (
        user_id BIGINT NOT NULL,
        symbol TEXT NOT NULL,
        quantity DOUBLE PRECISION NOT NULL DEFAULT 0,
        cost_basis DOUBLE PRECISION,
        purchase_date TEXT,
        account_name TEXT,
        created_at TEXT NOT NULL DEFAULT app_now_text(),
        updated_at TEXT NOT NULL DEFAULT app_now_text(),
        PRIMARY KEY (user_id, symbol),
        FOREIGN KEY (user_id, symbol) REFERENCES symbols(user_id, symbol) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS symbol_technical (
        user_id BIGINT NOT NULL,
        symbol TEXT NOT NULL,
        window_start TEXT,
        window_end TEXT,
        fib_anchor TEXT,
        trends_json TEXT NOT NULL DEFAULT '[]',
        fib_levels_json TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT NOT NULL DEFAULT app_now_text(),
        PRIMARY KEY (user_id, symbol),
        FOREIGN KEY (user_id, symbol) REFERENCES symbols(user_id, symbol) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS recommendation_changelog (
        id BIGSERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        symbol TEXT NOT NULL,
        old_action TEXT,
        new_action TEXT NOT NULL,
        old_confidence TEXT,
        new_confidence TEXT,
        provider TEXT,
        created_at TEXT NOT NULL DEFAULT app_now_text(),
        FOREIGN KEY (user_id, symbol) REFERENCES symbols(user_id, symbol) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS signal_outcomes (
        id BIGSERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        symbol TEXT NOT NULL,
        assessment_id BIGINT,
        kind TEXT NOT NULL,
        label TEXT NOT NULL,
        direction TEXT NOT NULL,
        entry_price DOUBLE PRECISION NOT NULL,
        horizon_days INTEGER NOT NULL,
        captured_at TEXT NOT NULL DEFAULT app_now_text(),
        eval_due_at TEXT NOT NULL,
        eval_price DOUBLE PRECISION,
        return_pct DOUBLE PRECISION,
        outcome TEXT,
        evaluated_at TEXT,
        FOREIGN KEY (user_id, symbol) REFERENCES symbols(user_id, symbol) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS app_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS simulation_snapshots (
        user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        payload JSONB NOT NULL,
        saved_at TEXT NOT NULL DEFAULT app_now_text()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS symbol_market (
        symbol TEXT PRIMARY KEY,
        current_price DOUBLE PRECISION,
        day_change_pct DOUBLE PRECISION,
        price_as_of TEXT,
        analyst_target_1y DOUBLE PRECISION,
        analyst_target_low DOUBLE PRECISION,
        analyst_target_high DOUBLE PRECISION,
        company_name TEXT,
        fundamentals_json JSONB,
        updated_at TEXT NOT NULL DEFAULT app_now_text()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS symbol_assessment (
        symbol TEXT NOT NULL,
        as_of_date TEXT NOT NULL,
        action TEXT NOT NULL,
        confidence TEXT NOT NULL,
        rationale TEXT NOT NULL,
        factors TEXT,
        trading_recommendation TEXT,
        provider TEXT NOT NULL,
        analysis_json JSONB,
        created_at TEXT NOT NULL DEFAULT app_now_text(),
        PRIMARY KEY (symbol, as_of_date)
    )
    """,
)

# Indexes are created after the multi-user migration so that user_id exists on
# legacy tables (which only gain the column during _migrate_to_multiuser).
INDEX_STATEMENTS: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_notes_user_symbol ON notes(user_id, symbol)",
    "CREATE INDEX IF NOT EXISTS idx_alerts_user_symbol ON alerts(user_id, symbol)",
    "CREATE INDEX IF NOT EXISTS idx_alerts_user_status ON alerts(user_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_assessments_user_symbol ON assessments(user_id, symbol)",
    "CREATE INDEX IF NOT EXISTS idx_reco_changelog_user_symbol ON recommendation_changelog(user_id, symbol)",
    "CREATE INDEX IF NOT EXISTS idx_reco_changelog_created ON recommendation_changelog(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_signal_outcomes_user ON signal_outcomes(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_signal_outcomes_pending ON signal_outcomes(user_id, outcome, eval_due_at)",
    "CREATE INDEX IF NOT EXISTS idx_symbol_market_updated ON symbol_market(updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_symbol_assessment_created ON symbol_assessment(created_at)",
)

# Idempotent column adds so an already-deployed Postgres picks up new columns
# without a manual migration. Safe to run on every boot.
MIGRATION_STATEMENTS: tuple[str, ...] = (
    "ALTER TABLE symbols ADD COLUMN IF NOT EXISTS annual_dividend DOUBLE PRECISION",
    "ALTER TABLE symbols ADD COLUMN IF NOT EXISTS trade_below_price DOUBLE PRECISION",
    "ALTER TABLE symbols ADD COLUMN IF NOT EXISTS trade_below_shares DOUBLE PRECISION",
    "ALTER TABLE symbols ADD COLUMN IF NOT EXISTS trade_above_price DOUBLE PRECISION",
    "ALTER TABLE symbols ADD COLUMN IF NOT EXISTS trade_above_shares DOUBLE PRECISION",
    "ALTER TABLE assessments ADD COLUMN IF NOT EXISTS note_synthesis TEXT",
    "ALTER TABLE assessments ADD COLUMN IF NOT EXISTS trading_recommendation TEXT",
    "ALTER TABLE notes ADD COLUMN IF NOT EXISTS synthesis TEXT",
    "ALTER TABLE notes ADD COLUMN IF NOT EXISTS synthesis_provider TEXT",
    "ALTER TABLE notes ADD COLUMN IF NOT EXISTS synthesized_at TEXT",
    "ALTER TABLE holdings ADD COLUMN IF NOT EXISTS purchase_date TEXT",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS picture TEXT",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TEXT",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS prefer_computed_trends BOOLEAN NOT NULL DEFAULT FALSE",
)

BOOTSTRAP_USER_EMAIL = os.environ.get("BOOTSTRAP_USER_EMAIL", "local@portfolio.local")

_pool: ConnectionPool | None = None

# Request-scoped current user. None outside a request; get_current_user_id()
# then falls back to the bootstrap user (single-user / scripts / background).
_current_user_id: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "current_user_id", default=None
)
_bootstrap_user_id: int | None = None


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


# --------------------------------------------------------------------------- #
# Current-user context + user records
# --------------------------------------------------------------------------- #
def set_current_user_id(user_id: int | None) -> contextvars.Token:
    """Bind the current user for this context (request/thread). Returns a token
    that can be passed to reset_current_user_id()."""
    return _current_user_id.set(user_id)


def reset_current_user_id(token: contextvars.Token) -> None:
    _current_user_id.reset(token)


def get_current_user_id() -> int:
    """Resolve the current user id, falling back to the bootstrap user when no
    request context has set one (scripts, background jobs, tests)."""
    user_id = _current_user_id.get()
    if user_id is not None:
        return user_id
    return get_bootstrap_user_id()


def reset_bootstrap_user_cache() -> None:
    """Clear the cached bootstrap user id. Needed after the users table is wiped
    (e.g. test schema resets) so the next resolution recreates the row."""
    global _bootstrap_user_id
    _bootstrap_user_id = None


def get_bootstrap_user_id() -> int:
    """Return the id of the single fallback user, creating it if needed.

    Used for single-user operation before OAuth and for any non-request code
    path. Cached after first resolution.
    """
    global _bootstrap_user_id
    if _bootstrap_user_id is not None:
        return _bootstrap_user_id
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO users (email, name) VALUES (%s, %s) ON CONFLICT (email) DO NOTHING",
            (BOOTSTRAP_USER_EMAIL, "Local User"),
        )
        row = conn.execute(
            "SELECT id FROM users WHERE email = %s", (BOOTSTRAP_USER_EMAIL,)
        ).fetchone()
        conn.commit()
    _bootstrap_user_id = int(row["id"])
    return _bootstrap_user_id


def get_or_create_user(
    google_sub: str, email: str, name: str | None = None, picture: str | None = None
) -> dict:
    """Upsert a user by Google subject id and return the stored record."""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO users (google_sub, email, name, picture, last_login_at)
            VALUES (%s, %s, %s, %s, app_now_text())
            ON CONFLICT (google_sub) DO UPDATE SET
                email = EXCLUDED.email,
                name = COALESCE(EXCLUDED.name, users.name),
                picture = COALESCE(EXCLUDED.picture, users.picture),
                last_login_at = app_now_text()
            """,
            (google_sub, email, name, picture),
        )
        row = conn.execute(
            "SELECT id, google_sub, email, name, picture FROM users WHERE google_sub = %s",
            (google_sub,),
        ).fetchone()
        conn.commit()
    return row


def get_user(user_id: int) -> dict | None:
    with get_connection() as conn:
        return conn.execute(
            "SELECT id, google_sub, email, name, picture FROM users WHERE id = %s",
            (user_id,),
        ).fetchone()


def get_prefer_computed_trends(user_id: int | None = None) -> bool:
    """Computed trends always win over imported TA snapshots."""
    return True


def set_prefer_computed_trends(value: bool, user_id: int | None = None) -> bool:
    uid = user_id if user_id is not None else get_current_user_id()
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET prefer_computed_trends = %s WHERE id = %s",
            (bool(value), uid),
        )
        conn.commit()
    return bool(value)


def list_distinct_symbols() -> list[str]:
    """Return every ticker tracked by any user (union across portfolios)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT DISTINCT symbol FROM symbols ORDER BY symbol"
        ).fetchall()
    return [row["symbol"] for row in rows]


def list_user_ids() -> list[int]:
    """Return all user ids (for per-user background jobs)."""
    with get_connection() as conn:
        rows = conn.execute("SELECT id FROM users ORDER BY id").fetchall()
    return [int(row["id"]) for row in rows]


# --------------------------------------------------------------------------- #
# Schema init + migrations
# --------------------------------------------------------------------------- #
def _column_exists(conn: psycopg.Connection, table: str, column: str) -> bool:
    return (
        conn.execute(
            """
            SELECT 1 FROM information_schema.columns
            WHERE table_name = %s AND column_name = %s
            """,
            (table, column),
        ).fetchone()
        is not None
    )


def _migrate_to_multiuser(conn: psycopg.Connection) -> None:
    """Transform a legacy single-user schema into the per-user schema.

    Adds user_id to every per-user table, backfills existing rows to a bootstrap
    user, and rebuilds primary/foreign keys as composite (user_id, symbol).
    Runs inside init_db's transaction so it is all-or-nothing; detection keys
    off the absence of symbols.user_id, so it is a no-op on the new schema.
    """
    if _column_exists(conn, "symbols", "user_id"):
        return  # already migrated / fresh install on the new schema

    conn.execute(
        "INSERT INTO users (email, name) VALUES (%s, %s) ON CONFLICT (email) DO NOTHING",
        (BOOTSTRAP_USER_EMAIL, "Local User"),
    )
    uid = conn.execute(
        "SELECT id FROM users WHERE email = %s", (BOOTSTRAP_USER_EMAIL,)
    ).fetchone()["id"]

    for table in PER_USER_TABLES:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS user_id BIGINT")
        conn.execute(f"UPDATE {table} SET user_id = %s WHERE user_id IS NULL", (uid,))

    # Drop legacy single-column foreign keys to symbols(symbol).
    for table in CHILD_TABLES:
        conn.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_symbol_fkey")

    # Rebuild primary keys as composite (user_id, symbol) where the PK was symbol.
    for table in ("symbols", "holdings", "symbol_technical"):
        conn.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_pkey")
        conn.execute(f"ALTER TABLE {table} ADD PRIMARY KEY (user_id, symbol)")

    for table in PER_USER_TABLES:
        conn.execute(f"ALTER TABLE {table} ALTER COLUMN user_id SET NOT NULL")

    conn.execute(
        "ALTER TABLE symbols ADD CONSTRAINT symbols_user_fkey "
        "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE"
    )
    for table in CHILD_TABLES:
        conn.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {table}_user_symbol_fkey "
            "FOREIGN KEY (user_id, symbol) REFERENCES symbols(user_id, symbol) ON DELETE CASCADE"
        )


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
                           PARTITION BY user_id, symbol ORDER BY created_at DESC, id DESC
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
    _backfill_symbol_market(conn)


def _symbols_has_market_columns(conn: psycopg.Connection) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'symbols'
          AND column_name = 'current_price'
        """
    ).fetchone()
    return row is not None


def _backfill_symbol_market(conn: psycopg.Connection) -> None:
    """Copy the newest per-user market columns into symbol_market (one row per ticker)."""
    row = conn.execute(
        "SELECT 1 FROM app_meta WHERE key = %s", ("symbol_market_backfill_v1",)
    ).fetchone()
    if row is not None:
        return
    if not _symbols_has_market_columns(conn):
        conn.execute(
            "INSERT INTO app_meta (key, value) VALUES (%s, app_now_text()) "
            "ON CONFLICT (key) DO NOTHING",
            ("symbol_market_backfill_v1",),
        )
        return
    conn.execute(
        """
        INSERT INTO symbol_market (
            symbol, current_price, day_change_pct, price_as_of,
            analyst_target_1y, analyst_target_low, analyst_target_high, updated_at
        )
        SELECT DISTINCT ON (symbol)
            symbol,
            current_price,
            day_change_pct,
            price_as_of,
            analyst_target_1y,
            analyst_target_low,
            analyst_target_high,
            updated_at
        FROM symbols
        WHERE current_price IS NOT NULL
           OR analyst_target_1y IS NOT NULL
           OR day_change_pct IS NOT NULL
        ORDER BY symbol, updated_at DESC NULLS LAST, user_id
        ON CONFLICT (symbol) DO UPDATE SET
            current_price = COALESCE(EXCLUDED.current_price, symbol_market.current_price),
            day_change_pct = COALESCE(EXCLUDED.day_change_pct, symbol_market.day_change_pct),
            price_as_of = COALESCE(EXCLUDED.price_as_of, symbol_market.price_as_of),
            analyst_target_1y = COALESCE(EXCLUDED.analyst_target_1y, symbol_market.analyst_target_1y),
            analyst_target_low = COALESCE(EXCLUDED.analyst_target_low, symbol_market.analyst_target_low),
            analyst_target_high = COALESCE(EXCLUDED.analyst_target_high, symbol_market.analyst_target_high),
            updated_at = GREATEST(EXCLUDED.updated_at, symbol_market.updated_at)
        """
    )
    conn.execute(
        "INSERT INTO app_meta (key, value) VALUES (%s, app_now_text()) "
        "ON CONFLICT (key) DO NOTHING",
        ("symbol_market_backfill_v1",),
    )


_SYMBOLS_MARKET_COLUMNS = (
    "current_price",
    "day_change_pct",
    "price_as_of",
    "analyst_target_1y",
    "analyst_target_low",
    "analyst_target_high",
)


def _slim_symbols_to_personal_only(conn: psycopg.Connection) -> None:
    """Drop market columns from per-user symbols; symbol_market is canonical."""
    row = conn.execute(
        "SELECT 1 FROM app_meta WHERE key = %s", ("symbols_slim_v1",)
    ).fetchone()
    if row is not None:
        return
    if _symbols_has_market_columns(conn):
        _backfill_symbol_market(conn)
    for column in _SYMBOLS_MARKET_COLUMNS:
        conn.execute(f"ALTER TABLE symbols DROP COLUMN IF EXISTS {column}")
    conn.execute(
        "INSERT INTO app_meta (key, value) VALUES (%s, app_now_text()) "
        "ON CONFLICT (key) DO NOTHING",
        ("symbols_slim_v1",),
    )


def _seed_trade_thresholds(conn: psycopg.Connection) -> None:
    """One-time seed of the new planned-trade price columns from the legacy
    buy_below/sell_above zones. Runs exactly once (guarded by an app_meta key);
    only fills NULL prices so it never clobbers user edits, and leaves the
    share-quantity columns NULL. Idempotent and safe on fresh installs (no rows
    to seed yet, but the guard is still set so it never re-runs)."""
    row = conn.execute(
        "SELECT 1 FROM app_meta WHERE key = %s", ("trade_thresholds_seeded",)
    ).fetchone()
    if row is not None:
        return
    conn.execute(
        """
        UPDATE symbols
        SET trade_below_price = buy_below
        WHERE trade_below_price IS NULL AND buy_below IS NOT NULL
        """
    )
    conn.execute(
        """
        UPDATE symbols
        SET trade_above_price = sell_above
        WHERE trade_above_price IS NULL AND sell_above IS NOT NULL
        """
    )
    conn.execute(
        "INSERT INTO app_meta (key, value) VALUES (%s, app_now_text()) "
        "ON CONFLICT (key) DO NOTHING",
        ("trade_thresholds_seeded",),
    )


def init_db() -> None:
    with get_connection() as conn:
        # 1. Base tables (fresh installs get the new per-user shape directly).
        for statement in SCHEMA_STATEMENTS:
            conn.execute(statement)
        # 2. Upgrade a legacy single-user schema to per-user (adds user_id, keys).
        _migrate_to_multiuser(conn)
        # 3. Idempotent column adds (safe once user_id-bearing tables exist).
        for statement in MIGRATION_STATEMENTS:
            conn.execute(statement)
        # 4. Indexes (now that user_id exists on every per-user table).
        for statement in INDEX_STATEMENTS:
            conn.execute(statement)
        # 5. Data-level migrations / cleanups.
        _run_data_migrations(conn)
        # 6. Drop legacy market columns from symbols (symbol_market is canonical).
        _slim_symbols_to_personal_only(conn)
        # 7. One-time seed of planned-trade prices from legacy buy/sell zones.
        _seed_trade_thresholds(conn)
        conn.commit()
