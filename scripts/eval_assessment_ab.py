#!/usr/bin/env python3
"""Rules-vs-LLM assessment A/B eval harness (read-only, never persists).

Measures whether the LLM adds value over the deterministic rules ladder, over a
real portfolio, WITHOUT writing to the live `assessments` table.

What it does
------------
1. Resolves a user (default: peroehner@gmail.com; falls back to the bootstrap user
   `local@portfolio.local`) and binds it as the current user.
2. For each portfolio symbol it snapshots the assessment INPUT context ONCE via
   `AssessmentService._build_context` (the exact bundle the real flow feeds the
   model). If that fails (e.g. no network for enrichment), it degrades to a
   DB-only minimal context so the rules side + threshold metric still run.
3. Generates two assessments per symbol from the SAME snapshot, calling the
   low-level `LLMClient.generate_assessment` directly (which does NOT touch the
   DB):
     - rules-only  (an LLMClient forced to mode="rules")
     - LLM         (gemini/openai) — only if a key is configured; else skipped.
4. Prints metrics: action distribution per mode, divergence rate, a heuristic
   "justified-divergence" flag, the stale-threshold-artifact count, and (if any
   evaluated `signal_outcomes` exist) a provider-tagged forward hit-rate.

Safety
------
Read-only w.r.t. real data: it issues only SELECTs and calls the in-memory
generation path (no INSERT/UPDATE into `assessments`/`signal_outcomes`). It does
NOT call `init_db()` and does NOT trigger track-record evaluation.

Usage
-----
    python scripts/eval_assessment_ab.py                 # default user, all symbols
    python scripts/eval_assessment_ab.py --email a@b.com  # a specific user
    python scripts/eval_assessment_ab.py --limit 8        # first 8 symbols (faster)
    python scripts/eval_assessment_ab.py --bootstrap      # force the bootstrap user
    python scripts/eval_assessment_ab.py --verbose        # per-symbol table

To exercise the LLM side, set a key first, e.g.:
    export GEMINI_API_KEY=...   (or OPENAI_API_KEY=...)
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

DEFAULT_EMAIL = "peroehner@gmail.com"
STALE_THRESHOLD_PCT = 0.20  # a hard BUY/SELL whose threshold is >20% off price


def _load_env() -> None:
    """Mirror main.load_env_file so DATABASE_URL / API keys are available."""
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


# Concrete-input citations we look for in an LLM rationale to judge whether a
# divergence is "justified" (grounded in a specific fact) vs vague reword.
_GROUNDING_PATTERNS: dict[str, str] = {
    "percent/target": r"\d+(?:\.\d+)?\s*%|analyst target|price target",
    "valuation (P/E, P/B)": r"\bp/?e\b|\bp/?b\b|forward pe|valuation|multiple",
    "cash flow / balance sheet": r"free cash flow|\bfcf\b|debt[\s-]?to[\s-]?equity|balance sheet",
    "technical (MA/Fib/RSI/MACD)": r"\b\d{1,3}-day\b|moving average|fib|retracement|\brsi\b|\bmacd\b|golden cross|death cross|200-day|50-day",
    "news/catalyst": r"\bnews\b|headline|earnings|guidance|upgrade|downgrade|catalyst",
}


def _grounding_hits(text: str) -> list[str]:
    low = (text or "").lower()
    return [name for name, pat in _GROUNDING_PATTERNS.items() if re.search(pat, low)]


def main() -> int:
    _load_env()

    parser = argparse.ArgumentParser(description="Rules-vs-LLM assessment A/B eval (read-only).")
    parser.add_argument("--email", default=DEFAULT_EMAIL, help="user email to evaluate")
    parser.add_argument("--bootstrap", action="store_true", help="force the bootstrap user")
    parser.add_argument("--limit", type=int, default=None, help="cap number of symbols")
    parser.add_argument("--verbose", action="store_true", help="print a per-symbol table")
    args = parser.parse_args()

    # Imports happen after _load_env so DATABASE_URL is set before the pool opens.
    from db.database import (
        BOOTSTRAP_USER_EMAIL,
        get_connection,
        set_current_user_id,
    )
    from services.assessment_service import AssessmentService
    from services.llm_client import LLMClient

    # --- Resolve user (SELECT only; never creates a user) --------------------
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
        print(f"ERROR: no user found for {args.email!r} or bootstrap. Nothing to do.")
        return 1
    set_current_user_id(user_id)
    print(f"User: id={user_id} <{email}>")

    # --- Row-count guard: prove we never write to `assessments` --------------
    def assessment_count() -> int:
        with get_connection() as conn:
            return int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM assessments WHERE user_id = %s", (user_id,)
                ).fetchone()["n"]
            )

    rows_before = assessment_count()

    svc = AssessmentService()
    symbols = [s["symbol"] for s in svc.portfolio_service.list_symbols()]
    if args.limit is not None:
        symbols = symbols[: args.limit]
    if not symbols:
        print("No symbols in portfolio for this user.")
        return 0
    print(f"Symbols to evaluate: {len(symbols)}")

    # --- LLM availability ----------------------------------------------------
    rules_client = LLMClient()
    rules_client.mode = "rules"  # force the deterministic path regardless of env
    llm_client = LLMClient()
    llm_provider = llm_client.active_provider()
    llm_enabled = llm_provider in ("openai", "gemini")
    if llm_enabled:
        model = llm_client.openai_model if llm_provider == "openai" else llm_client.gemini_model
        print(f"LLM side: ENABLED via {llm_provider} ({model})")
    else:
        print(
            "LLM side: SKIPPED — no API key configured. "
            "Set GEMINI_API_KEY or OPENAI_API_KEY (and optionally ASSESSMENT_MODE) to enable it."
        )

    def build_context(symbol: str) -> tuple[dict, str]:
        """Full context via the real builder; DB-only minimal fallback on failure."""
        symbol_data = svc.portfolio_service.get_symbol(symbol)
        if symbol_data is None:
            return {"symbol": symbol}, "missing"
        try:
            return svc._build_context(symbol_data), "full"
        except Exception as exc:  # noqa: BLE001 - eval must survive a bad symbol
            alerts = svc.alerts_service.list_alerts(symbol=symbol, status="active")
            minimal = {
                "symbol": symbol,
                "currentPrice": symbol_data.get("currentPrice"),
                "targetPrice": symbol_data.get("targetPrice"),
                "analystTarget1y": symbol_data.get("analystTarget1y"),
                "buyBelow": symbol_data.get("buyBelow"),
                "sellAbove": symbol_data.get("sellAbove"),
                "alerts": alerts,
                "noteSyntheses": [],
                "screening": {},
                "fundamentals": {},
                "recentNews": [],
                "technical": None,
                "holding": None,
            }
            if args.verbose:
                print(f"  ! {symbol}: full context failed ({type(exc).__name__}); using minimal. {exc}")
            return minimal, "minimal"

    rules_actions: Counter = Counter()
    llm_actions: Counter = Counter()
    ctx_modes: Counter = Counter()
    divergences = 0
    justified = 0
    artifacts: list[dict] = []
    per_symbol: list[dict] = []

    for symbol in symbols:
        context, ctx_mode = build_context(symbol)
        ctx_modes[ctx_mode] += 1

        # Stale-threshold artifact: a hard BUY/SELL whose threshold is >20% off price.
        hard = LLMClient.hard_trigger(context)
        if hard is not None:
            price = context.get("currentPrice")
            thr = context.get("sellAbove") if hard["action"] == "sell" else context.get("buyBelow")
            if price and thr and price > 0 and abs(price - thr) / price > STALE_THRESHOLD_PCT:
                artifacts.append(
                    {"symbol": symbol, "action": hard["action"], "price": price,
                     "threshold": thr, "offPct": round(abs(price - thr) / price * 100, 1)}
                )

        rules_res = rules_client.generate_assessment(context)
        rules_actions[rules_res["action"]] += 1

        llm_res = None
        if llm_enabled:
            llm_res = llm_client.generate_assessment(context)
            llm_actions[llm_res["action"]] += 1
            if llm_res["action"] != rules_res["action"]:
                divergences += 1
                hits = _grounding_hits(
                    str(llm_res.get("rationale", "")) + " " + " ".join(llm_res.get("factors", []))
                )
                if hits:
                    justified += 1

        per_symbol.append({
            "symbol": symbol,
            "ctx": ctx_mode,
            "rules": f'{rules_res["action"]}/{rules_res["confidence"]}',
            "rulesSource": rules_res.get("actionSource"),
            "llm": (f'{llm_res["action"]}/{llm_res["confidence"]}' if llm_res else "-"),
            "llmSource": (llm_res.get("actionSource") if llm_res else "-"),
        })

    rows_after = assessment_count()

    # ----------------------------- report -----------------------------------
    def hr(t: str) -> None:
        print("\n" + "=" * 64 + "\n" + t + "\n" + "=" * 64)

    if args.verbose:
        hr("PER-SYMBOL")
        print(f'{"SYMBOL":8}{"CTX":9}{"RULES":18}{"RULES_SRC":20}{"LLM":14}{"LLM_SRC"}')
        for r in per_symbol:
            print(f'{r["symbol"]:8}{r["ctx"]:9}{r["rules"]:18}{str(r["rulesSource"]):20}{r["llm"]:14}{r["llmSource"]}')

    hr("CONTEXT SNAPSHOTS")
    print(dict(ctx_modes), "(full = real builder; minimal = DB-only fallback)")

    hr("ACTION DISTRIBUTION")
    print("rules-only:", dict(rules_actions))
    print("llm       :", dict(llm_actions) if llm_enabled else "(skipped — no key)")

    hr("DIVERGENCE (LLM action != rules action)")
    if llm_enabled:
        n = len(symbols)
        rate = round(divergences / n * 100, 1) if n else 0.0
        jrate = round(justified / divergences * 100, 1) if divergences else 0.0
        print(f"divergences: {divergences}/{n} ({rate}%)")
        print(f"justified (LLM rationale cites a concrete input): {justified}/{divergences} ({jrate}%)")
    else:
        print("skipped — no LLM key configured.")

    hr("STALE-THRESHOLD ARTIFACTS (hard BUY/SELL with threshold >20% off price)")
    if artifacts:
        for a in artifacts:
            print(f'  {a["symbol"]:8} {a["action"].upper():4} price={a["price"]} threshold={a["threshold"]} ({a["offPct"]}% off)')
        print(f"total: {len(artifacts)}")
    else:
        print("none")

    hr("FORWARD HIT-RATE (evaluated signal_outcomes, kind='recommendation')")
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT COALESCE(a.provider, 'unknown') AS provider, so.outcome, COUNT(*) AS n
            FROM signal_outcomes so
            LEFT JOIN assessments a ON a.id = so.assessment_id
            WHERE so.user_id = %s AND so.kind = 'recommendation' AND so.outcome IS NOT NULL
            GROUP BY COALESCE(a.provider, 'unknown'), so.outcome
            ORDER BY provider
            """,
            (user_id,),
        ).fetchall()
    if not rows:
        print("no evaluated recommendation outcomes yet (need elapsed 21-day horizons).")
    else:
        by_provider: dict[str, Counter] = {}
        for r in rows:
            by_provider.setdefault(r["provider"], Counter())[r["outcome"]] += r["n"]
        for provider, c in by_provider.items():
            decided = c.get("win", 0) + c.get("loss", 0)
            hit = round(c.get("win", 0) / decided * 100, 1) if decided else None
            print(f'  {provider:8} wins={c.get("win",0)} losses={c.get("loss",0)} '
                  f'neutrals={c.get("neutral",0)} hit-rate={hit}%')

    hr("WRITE-SAFETY CHECK")
    print(f"assessments row-count before={rows_before} after={rows_after} "
          f"-> {'UNCHANGED (read-only OK)' if rows_before == rows_after else 'CHANGED (!) investigate'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
