# Data & persistence

This document is the canonical reference for what the Portfolio Dashboard Agent stores, where it lives, and what is ephemeral. **Update this file and the [README](../README.md) § Data & persistence whenever persistence behavior changes.**

## Files to update when changing storage

| Change | Update |
|--------|--------|
| New/altered Postgres table or column | `db/database.py`, this doc, README § Data & persistence |
| Import merge/replace or new import fields | `services/import_service.py`, this doc |
| New persisted API writes | relevant `services/*.py`, `docs/API.md` if public |
| Background sync interval or cached fields | `main.py`, `api/v1.py` `/config`, this doc |
| Browser `localStorage` or client-only state | `dashboard.html`, this doc |
| OAuth / multi-user behavior | `auth.py`, `.env.example`, this doc |

## Storage location

Storage is **Postgres** (psycopg3 + connection pool). Connection string comes
from `DATABASE_URL`.

| Environment | Source of `DATABASE_URL` |
|-------------|--------------------------|
| Local dev | `docker compose up -d db` or Postgres.app → see `.env.example` |
| Render | Managed Postgres, set in dashboard / `render.yaml` |

Schema and migrations: `db/database.py` (`init_db()` on first request). Migrating
from a legacy SQLite file: `python scripts/migrate_sqlite_to_postgres.py`.

## Multi-user model

When Google OAuth is configured (`GOOGLE_OAUTH_CLIENT_ID` + `GOOGLE_OAUTH_CLIENT_SECRET`), each signed-in Google account gets its own scoped portfolio. Per-user tables are keyed by `(user_id, symbol)`; the request auth guard binds `user_id` from the Flask session on every API call.

Without OAuth, the app runs in **single-user mode**: all data lives under a bootstrap user (`BOOTSTRAP_USER_EMAIL`, default `local@portfolio.local`).

Optional `ALLOWED_EMAILS` restricts who may sign in (comma-separated).

## Tables

### `users`

Google OAuth identity and preferences (`prefer_computed_trends`, etc.).

### `symbols` (per user)

Personal thresholds and targets only — **not** live market quotes.

| Column | Persisted | Notes |
|--------|-----------|-------|
| `target_price` | Yes | Personal target |
| `buy_below`, `sell_above` | Yes | Legacy zones; mirrored from trade thresholds |
| `trade_below_*`, `trade_above_*` | Yes | Planned trade levels + share quantities |
| `annual_dividend` | Yes | Often from import |

API: `GET/PUT /api/v1/symbols/{symbol}`, import.

Reads join `symbol_market` for `currentPrice`, `dayChangePct`, analyst targets.

### `symbol_market` (shared)

One row per ticker across all users. Written by background price sync and optional import hints.

| Column | Notes |
|--------|-------|
| `current_price`, `day_change_pct`, `price_as_of` | yfinance sync |
| `analyst_target_1y`, `analyst_target_low/high` | yfinance sync (~hourly) |
| `company_name` | From quotes when available |
| `fundamentals_json` | Shared fundamentals cache (`SYMBOL_MARKET_FUNDAMENTALS`) |

### `symbol_assessment` (shared)

One **base** LLM assessment per symbol per UTC day (`DEDUP_BASE_ASSESSMENT=1`). Personal thresholds and notes are applied afterward via `AssessmentOverlayService` and stored in per-user `assessments`.

Pre-warmed by the daily assessment worker (`DAILY_ASSESSMENT_WORKER=1`) after price sync.

### `holdings`

Position size and cost basis per symbol (per user).

API: `GET/POST/PUT/DELETE /api/v1/holdings`, import.

### `notes`

User-authored text; optional LLM synthesis stored on the same row (`synthesis`, `synthesis_provider`, `synthesized_at`).

API: `GET/POST /api/v1/symbols/{symbol}/notes`, synthesize endpoints.

**Not imported** from analyst files.

### `assessments` (per user)

Overlay result per Assess Symbol run (historical list in Inspector). When dedup is on, the LLM call is shared via `symbol_assessment`; this table stores the user-specific overlay output.

API: `POST /api/v1/symbols/{symbol}/assess`, `GET /api/v1/assessments`.

### `alerts` (per user)

Rule-generated messages; dismiss sets `status = 'dismissed'`.

Created by `AlertsService.evaluate_all()` during background sync (once per user). API: `GET /api/v1/alerts`, dismiss endpoint.

### `symbol_technical` (per user)

Parsed TA export per symbol: `window_start`, `window_end`, `fib_anchor`, `trends_json`, `fib_levels_json`.

Written on TA import via `TechnicalService.upsert_snapshot()`. Read by Inspector for trend waves, imported fib levels, and chart window bounds.

## Import pipeline

```
Upload (JSON / CSV / TA .txt)
    → ImportService.import_file() / import_payload()
    → PortfolioService.upsert_symbol()     (personal fields)
    → MarketDataService.seed_from_import() (optional price / analyst hints → symbol_market)
    → HoldingsService.upsert_holding() (if qty/cost in payload)
    → TechnicalService.upsert_snapshot() (if _technical in payload)
    → Postgres
```

- Raw upload bytes are **not** archived.
- **merge**: upsert only; existing notes/assessments/alerts remain for symbols not removed.
- **replace**: `PortfolioService.clear_portfolio()` for the **current user only**, then import (cascade deletes that user's child rows).

## Background sync

`main.py` → `background_sync_loop()` every 300s:

1. **Global price fetch** — union of all users' tickers → `symbol_market` via `MarketDataService.sync_quotes()`
2. **Per-user alerts** — `AlertsService.evaluate_all()` for each `user_id`
3. **Daily base assessments** (once per UTC day) — `DailyAssessmentService.run_daily_assessments()` → `symbol_assessment`

Manual sync: legacy `GET /api/sync` or UI **Sync Prices** (same price update path).

## Ephemeral / on-demand data

Not stored in Postgres; fetched when an endpoint or UI view needs it:

| Concern | Service | Mechanism |
|---------|---------|-----------|
| Screening scores & flags | `ScreeningService` | `symbols` + `symbol_market` join + `FibService` + `alerts` |
| Inspector P/E, PEG, growth, margin | `InspectorService` | `FundamentalsService` (DB cache + yfinance) |
| Recent news headlines | `FundamentalsService` | In-memory TTL cache (not in `symbol_market`) |
| Fib without TA import | `FibService` | 90d history (`FIB_LOOKBACK_PERIOD`) |
| Inspector chart timeline | `TechnicalService.chart_timeline()` | yfinance over import window |
| Trend leg peak high/low | `TechnicalService._peaks_for_date_range()` | yfinance |
| Overview YTD | `OverviewService` | yfinance year-start closes |
| Sentiment (optional) | `PortfolioEngine` | In-process transformers model |

## Client (browser) state

| State | Persistence |
|-------|-------------|
| Portfolio, notes, assessments, alerts | None locally — always from API (session-scoped) |
| `pda_synthesis_guidance` | `localStorage` (per browser) |
| Table sort, selected symbol, fib toggles, chart mode | JavaScript memory — lost on reload |
| Screening / fib view cache | In-memory ~60s (`VIEW_CACHE_TTL_MS`) — not shared across users if session changes (page reloads on user switch) |

Use **separate browsers or profiles** for local multi-user testing — one session cookie per browser.

## Cloud deployment notes

- **Shared Postgres, isolated portfolios**: one database per deployed instance; each OAuth user has separate rows keyed by `user_id`.
- **OAuth (production)**: set `SESSION_SECRET`, `GOOGLE_OAUTH_CLIENT_*`, `OAUTH_REDIRECT_URI` (must match Google console exactly), `SESSION_COOKIE_SECURE=1` on HTTPS. Optional `ALLOWED_EMAILS`.
- **Persistence**: managed Postgres survives redeploys. Render's `free` DB plan expires after 30 days; use `basic-256mb` or larger for production.
- **LLM secrets**: `OPENAI_API_KEY`, `GEMINI_API_KEY`, etc. live in platform env vars only.
- **Re-import after redeploy**: keep export JSON locally to restore per-user state.

## Quick reference: durable vs ephemeral

**Survives restart** (durable in Postgres): per-user symbols/thresholds, holdings, notes, assessments, alerts, TA trends/fibs; shared `symbol_market` prices/fundamentals; shared daily `symbol_assessment` base rows.

**Refreshed on schedule**: `symbol_market` prices (~5 min), analyst targets (~1 h), fundamentals TTL (`SYMBOL_MARKET_FUNDAMENTALS_TTL_SECONDS`), daily base assessments (UTC day).

**Always live**: news headlines, auto fibs, chart series, screening scores, overview YTD.

**Never stored**: original import file blob.
