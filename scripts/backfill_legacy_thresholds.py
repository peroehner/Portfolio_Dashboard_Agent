#!/usr/bin/env python3
"""Sync the legacy buy_below/sell_above columns from the user-edited trade levels.

The Target screen writes the user's real thresholds into
`symbols.trade_below_price` / `symbols.trade_above_price`, but legacy readers
still key off `symbols.buy_below` / `symbols.sell_above`. New saves now mirror the
trade levels into the legacy columns automatically (see
PortfolioService.upsert_symbol); this one-time, idempotent backfill reconciles
EXISTING rows.

Per-column rule: a legacy column is overwritten ONLY when its trade_* counterpart
is non-NULL. trade_* stays the source of truth — this script never touches it.

Usage:
    python scripts/backfill_legacy_thresholds.py             # dry-run preview (default)
    python scripts/backfill_legacy_thresholds.py --dry-run   # explicit dry-run
    python scripts/backfill_legacy_thresholds.py --apply     # write legacy columns
    python scripts/backfill_legacy_thresholds.py --user-id 7 --apply
    python scripts/backfill_legacy_thresholds.py --email a@b.com --apply
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

DEFAULT_USER_ID = 7


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

    parser = argparse.ArgumentParser(
        description="Mirror trade_below_price/trade_above_price into legacy buy_below/sell_above."
    )
    parser.add_argument("--user-id", type=int, default=DEFAULT_USER_ID, help="user id to backfill")
    parser.add_argument("--email", default=None, help="resolve user by email (overrides --user-id)")
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    parser.add_argument("--dry-run", action="store_true", help="preview only (default)")
    args = parser.parse_args()

    from db.database import get_connection, set_current_user_id

    user_id = args.user_id
    if args.email:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT id, email FROM users WHERE email = %s", (args.email,)
            ).fetchone()
        if row is None:
            print(f"ERROR: no user found for {args.email!r}.")
            return 1
        user_id = int(row["id"])
        print(f"User: id={user_id} <{row['email']}>")
    else:
        print(f"User: id={user_id}")

    set_current_user_id(user_id)

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT symbol, buy_below, sell_above, trade_below_price, trade_above_price
            FROM symbols
            WHERE user_id = %s
              AND (
                (trade_below_price IS NOT NULL AND buy_below IS DISTINCT FROM trade_below_price)
                OR (trade_above_price IS NOT NULL AND sell_above IS DISTINCT FROM trade_above_price)
              )
            ORDER BY symbol
            """,
            (user_id,),
        ).fetchall()

    if not rows:
        print("Nothing to do — legacy columns already match trade levels.")
        return 0

    print(f"Rows needing sync: {len(rows)}")
    for r in rows:
        changes = []
        if r["trade_below_price"] is not None and r["buy_below"] != r["trade_below_price"]:
            changes.append(f"buy_below {r['buy_below']} -> {r['trade_below_price']}")
        if r["trade_above_price"] is not None and r["sell_above"] != r["trade_above_price"]:
            changes.append(f"sell_above {r['sell_above']} -> {r['trade_above_price']}")
        print(f"  {r['symbol']:8} {'; '.join(changes)}")

    apply = args.apply and not args.dry_run
    if not apply:
        print("\nDRY RUN — re-run with --apply to write. No rows modified.")
        return 0

    with get_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE symbols
            SET buy_below = CASE
                    WHEN trade_below_price IS NOT NULL THEN trade_below_price
                    ELSE buy_below
                END,
                sell_above = CASE
                    WHEN trade_above_price IS NOT NULL THEN trade_above_price
                    ELSE sell_above
                END,
                updated_at = app_now_text()
            WHERE user_id = %s
              AND (
                (trade_below_price IS NOT NULL AND buy_below IS DISTINCT FROM trade_below_price)
                OR (trade_above_price IS NOT NULL AND sell_above IS DISTINCT FROM trade_above_price)
              )
            """,
            (user_id,),
        )
        conn.commit()
        print(f"\nApplied. rows updated={cursor.rowcount}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
