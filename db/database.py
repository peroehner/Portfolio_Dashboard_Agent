import os
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BASE_DIR / "data" / "portfolio.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS symbols (
    symbol TEXT PRIMARY KEY,
    current_price REAL,
    target_price REAL,
    buy_below REAL,
    sell_above REAL,
    annual_dividend REAL,
    analyst_target_1y REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    note_date TEXT,
    source TEXT,
    text TEXT NOT NULL,
    synthesis TEXT,
    synthesis_provider TEXT,
    synthesized_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (symbol) REFERENCES symbols(symbol) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_notes_symbol ON notes(symbol);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    alert_type TEXT NOT NULL,
    message TEXT NOT NULL,
    price REAL,
    reference_value REAL,
    fib_level TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (symbol) REFERENCES symbols(symbol) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_alerts_symbol ON alerts(symbol);
CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(status);

CREATE TABLE IF NOT EXISTS assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    action TEXT NOT NULL,
    confidence TEXT NOT NULL,
    rationale TEXT NOT NULL,
    factors TEXT,
    note_synthesis TEXT,
    trading_recommendation TEXT,
    provider TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (symbol) REFERENCES symbols(symbol) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_assessments_symbol ON assessments(symbol);

CREATE TABLE IF NOT EXISTS holdings (
    symbol TEXT PRIMARY KEY,
    quantity REAL NOT NULL DEFAULT 0,
    cost_basis REAL,
    purchase_date TEXT,
    account_name TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (symbol) REFERENCES symbols(symbol) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS symbol_technical (
    symbol TEXT PRIMARY KEY,
    window_start TEXT,
    window_end TEXT,
    fib_anchor TEXT,
    trends_json TEXT NOT NULL DEFAULT '[]',
    fib_levels_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (symbol) REFERENCES symbols(symbol) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS recommendation_changelog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    old_action TEXT,
    new_action TEXT NOT NULL,
    old_confidence TEXT,
    new_confidence TEXT,
    provider TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (symbol) REFERENCES symbols(symbol) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_reco_changelog_symbol ON recommendation_changelog(symbol);
CREATE INDEX IF NOT EXISTS idx_reco_changelog_created ON recommendation_changelog(created_at);
"""


def get_db_path() -> Path:
    return Path(os.environ.get("DATABASE_PATH", DEFAULT_DB_PATH))


def get_connection() -> sqlite3.Connection:
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migrate_schema(conn: sqlite3.Connection) -> None:
    symbol_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(symbols)")
    }
    if "annual_dividend" not in symbol_columns:
        conn.execute("ALTER TABLE symbols ADD COLUMN annual_dividend REAL")
    if "analyst_target_1y" not in symbol_columns:
        conn.execute("ALTER TABLE symbols ADD COLUMN analyst_target_1y REAL")
        conn.execute(
            """
            UPDATE symbols
            SET analyst_target_1y = target_price
            WHERE analyst_target_1y IS NULL AND target_price IS NOT NULL
            """
        )
    if "day_change_pct" not in symbol_columns:
        conn.execute("ALTER TABLE symbols ADD COLUMN day_change_pct REAL")

    assessment_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(assessments)")
    }
    if "note_synthesis" not in assessment_columns:
        conn.execute("ALTER TABLE assessments ADD COLUMN note_synthesis TEXT")
    if "trading_recommendation" not in assessment_columns:
        conn.execute("ALTER TABLE assessments ADD COLUMN trading_recommendation TEXT")

    note_columns = {row[1] for row in conn.execute("PRAGMA table_info(notes)")}
    if "synthesis" not in note_columns:
        conn.execute("ALTER TABLE notes ADD COLUMN synthesis TEXT")
    if "synthesis_provider" not in note_columns:
        conn.execute("ALTER TABLE notes ADD COLUMN synthesis_provider TEXT")
    if "synthesized_at" not in note_columns:
        conn.execute("ALTER TABLE notes ADD COLUMN synthesized_at TEXT")

    holding_columns = {row[1] for row in conn.execute("PRAGMA table_info(holdings)")}
    if "purchase_date" not in holding_columns:
        conn.execute("ALTER TABLE holdings ADD COLUMN purchase_date TEXT")

    tables = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    if "symbol_technical" not in tables:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS symbol_technical (
                symbol TEXT PRIMARY KEY,
                window_start TEXT,
                window_end TEXT,
                fib_anchor TEXT,
                trends_json TEXT NOT NULL DEFAULT '[]',
                fib_levels_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (symbol) REFERENCES symbols(symbol) ON DELETE CASCADE
            );
            """
        )
    if "recommendation_changelog" not in tables:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS recommendation_changelog (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                old_action TEXT,
                new_action TEXT NOT NULL,
                old_confidence TEXT,
                new_confidence TEXT,
                provider TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (symbol) REFERENCES symbols(symbol) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_reco_changelog_symbol ON recommendation_changelog(symbol);
            CREATE INDEX IF NOT EXISTS idx_reco_changelog_created ON recommendation_changelog(created_at);
            """
        )


def _ensure_app_meta(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )


def _migration_applied(conn: sqlite3.Connection, key: str) -> bool:
    row = conn.execute("SELECT 1 FROM app_meta WHERE key = ?", (key,)).fetchone()
    return row is not None


def _mark_migration_applied(conn: sqlite3.Connection, key: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO app_meta (key, value) VALUES (?, datetime('now'))",
        (key,),
    )


def _run_data_migrations(conn: sqlite3.Connection) -> None:
    _ensure_app_meta(conn)
    if _migration_applied(conn, "assessment_max3_cleanup_v1"):
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
    _mark_migration_applied(conn, "assessment_max3_cleanup_v1")


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        _migrate_schema(conn)
        _run_data_migrations(conn)
        conn.commit()
