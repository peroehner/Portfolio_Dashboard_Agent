#!/usr/bin/env python3
"""Profile Screening and Fib Proximity hot paths."""
from __future__ import annotations

import cProfile
import io
import os
import pstats
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SYMBOLS = [
    "AMZN", "IBRX", "SAP", "CRSP", "QBTS", "RGTI",
    "CRWV", "DOCU", "HUBS", "MELI", "MGNI", "OTEX",
]


def seed_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
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
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            message TEXT NOT NULL,
            price REAL,
            reference_value REAL,
            fib_level TEXT,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
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
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS holdings (
            symbol TEXT PRIMARY KEY,
            quantity REAL NOT NULL DEFAULT 0,
            cost_basis REAL,
            purchase_date TEXT,
            account_name TEXT,
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
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )
    for symbol in SYMBOLS:
        conn.execute(
            """
            INSERT OR REPLACE INTO symbols (
                symbol, current_price, target_price, buy_below, sell_above, analyst_target_1y
            ) VALUES (?, 100.0, 130.0, 90.0, 140.0, 125.0)
            """,
            (symbol,),
        )
    conn.commit()
    conn.close()


def count_yfinance_calls() -> dict[str, int]:
    import yfinance as yf

    counts = {"history": 0, "download": 0}

    original_history = yf.Ticker.history

    def wrapped_history(self, *args, **kwargs):
        counts["history"] += 1
        return original_history(self, *args, **kwargs)

    yf.Ticker.history = wrapped_history
    return counts


def print_top_stats(profiler: cProfile.Profile, limit: int = 15) -> None:
    stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stream)
    stats.sort_stats("cumulative")
    stats.print_stats(limit)
    print(stream.getvalue())


def main() -> None:
    db_path = ROOT / "data" / "profile_temp.db"
    os.environ["DATABASE_PATH"] = str(db_path)
    seed_db(db_path)

    from services.fib_service import FibService
    from services.screening_service import ScreeningService

    counts = count_yfinance_calls()
    service = ScreeningService()
    expected_calls = len(SYMBOLS)

    print(f"Symbols: {len(SYMBOLS)}")
    print(f"Expected yfinance calls per endpoint (cold cache): {expected_calls}")
    print("=" * 60)
    print("FIB PROXIMITY MAP (cold cache)")
    FibService.clear_cache()
    counts["history"] = 0
    t0 = time.perf_counter()
    profiler = cProfile.Profile()
    profiler.enable()
    service.fib_proximity_map()
    profiler.disable()
    fib_elapsed = time.perf_counter() - t0
    fib_calls = counts["history"]
    print(f"Wall time: {fib_elapsed:.2f}s")
    print(f"yfinance Ticker.history calls: {fib_calls}")
    print_top_stats(profiler)

    print("=" * 60)
    print("FIB PROXIMITY MAP (warm cache)")
    counts["history"] = 0
    t0 = time.perf_counter()
    service.fib_proximity_map()
    fib_warm_elapsed = time.perf_counter() - t0
    fib_warm_calls = counts["history"]
    print(f"Wall time: {fib_warm_elapsed:.4f}s")
    print(f"yfinance Ticker.history calls: {fib_warm_calls}")

    print("=" * 60)
    print("SCREENING (run_screen, cold cache)")
    FibService.clear_cache()
    counts["history"] = 0
    t0 = time.perf_counter()
    profiler = cProfile.Profile()
    profiler.enable()
    service.run_screen()
    profiler.disable()
    screen_elapsed = time.perf_counter() - t0
    screen_calls = counts["history"]
    print(f"Wall time: {screen_elapsed:.2f}s")
    print(f"yfinance Ticker.history calls: {screen_calls}")
    print_top_stats(profiler)

    print("=" * 60)
    print("SUMMARY")
    print(f"Fib map total: {fib_elapsed:.2f}s (~{fib_elapsed / len(SYMBOLS):.2f}s/symbol)")
    print(f"Fib map warm: {fib_warm_elapsed:.4f}s, {fib_warm_calls} yfinance calls")
    print(f"Screening total: {screen_elapsed:.2f}s (~{screen_elapsed / len(SYMBOLS):.2f}s/symbol)")
    if fib_calls != expected_calls:
        print(f"NOTE: fib map used {fib_calls} calls (expected {expected_calls})")
    if screen_calls != expected_calls:
        print(f"NOTE: screening used {screen_calls} calls (expected {expected_calls})")


if __name__ == "__main__":
    main()
