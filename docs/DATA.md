# Data & persistence

This document is the canonical reference for what the Portfolio Dashboard Agent stores, where it lives, and what is ephemeral. **Update this file and the [README](../README.md) § Data & persistence whenever persistence behavior changes.**

## Files to update when changing storage

| Change | Update |
|--------|--------|
| New/altered SQLite table or column | `db/database.py`, this doc, README § Data & persistence |
| Import merge/replace or new import fields | `services/import_service.py`, this doc |
| New persisted API writes | relevant `services/*.py`, `docs/API.md` if public |
| Background sync interval or cached fields | `main.py`, `api/v1.py` `/config`, this doc |
| Browser `localStorage` or client-only state | `dashboard.html`, this doc |

## Storage location

| Environment | Default path | Override |
|-------------|--------------|----------|
| Local dev | `data/portfolio.db` (repo-relative) | `DATABASE_PATH` in `.env` |
| Render (ephemeral) | `data/portfolio.db` on instance disk | — |
| Render (persistent) | `/var/data/portfolio.db` | `DATABASE_PATH` + attached disk in `render.yaml` |

Schema and migrations: `db/database.py` (`init_db()` on first request).

## SQLite tables

### `symbols`

Core quote and threshold row per ticker.

| Column | Persisted | Notes |
|--------|-----------|-------|
| `current_price` | Yes | Updated by background sync + import |
| `target_price` | Yes | Personal target |
| `buy_below`, `sell_above` | Yes | User thresholds |
| `annual_dividend` | Yes | Often from import |
| `analyst_target_1y` | Yes | Sync + import |

API: `GET/PUT /api/v1/symbols/{symbol}`, import, `POST /api/sync` (legacy).

### `holdings`

Position size and cost basis per symbol.

API: `GET/POST/PUT/DELETE /api/v1/holdings`, import.

### `notes`

User-authored text; optional LLM synthesis stored on the same row (`synthesis`, `synthesis_provider`, `synthesized_at`).

API: `GET/POST /api/v1/symbols/{symbol}/notes`, synthesize endpoints.

**Not imported** from analyst files.

### `assessments`

One row per Assess Symbol run (historical list in Inspector).

API: `POST /api/v1/symbols/{symbol}/assess`, `GET /api/v1/assessments`.

### `alerts`

Rule-generated messages; dismiss sets `status = 'dismissed'`.

Created by `AlertsService.evaluate_all()` during background sync. API: `GET /api/v1/alerts`, dismiss endpoint.

### `symbol_technical`

Parsed TA export per symbol: `window_start`, `window_end`, `fib_anchor`, `trends_json`, `fib_levels_json`.

Written on TA import via `TechnicalService.upsert_snapshot()`. Read by Inspector for trend waves, imported fib levels, and chart window bounds.

## Import pipeline

```
Upload (JSON / CSV / TA .txt)
    → ImportService.import_file() / import_payload()
    → PortfolioService.upsert_symbol()
    → HoldingsService.upsert_holding() (if qty/cost in payload)
    → TechnicalService.upsert_snapshot() (if _technical in payload)
    → SQLite
```

- Raw upload bytes are **not** archived.
- **merge**: upsert only; existing notes/assessments/alerts remain for symbols not removed.
- **replace**: `PortfolioService.clear_portfolio()` then import (cascade deletes all child rows).

## Background sync

`main.py` → `background_sync_loop()` every 300s:

1. `PortfolioService.sync_prices(engine)` — yfinance → `symbols.current_price`, `symbols.analyst_target_1y`
2. `AlertsService.evaluate_all(engine)` — may insert new `alerts` rows

Manual sync: legacy `GET /api/sync` or UI **Sync Prices** (same price update path).

## Ephemeral / on-demand data

Not stored in SQLite; fetched when an endpoint or UI view needs it:

| Concern | Service | Mechanism |
|---------|---------|-----------|
| Screening scores & flags | `ScreeningService` | Derived from `symbols` + `FibService` + `alerts` |
| Inspector P/E, PEG, growth, margin | `InspectorService._valuation_metrics()` | `yfinance.Ticker.info` |
| Fib without TA import | `FibService` | 90d history (`FIB_LOOKBACK_PERIOD`) |
| Inspector chart timeline | `TechnicalService.chart_timeline()` | yfinance over import window |
| Trend leg peak high/low | `TechnicalService._peaks_for_date_range()` | yfinance |
| Overview YTD | `OverviewService` | yfinance year-start closes |
| Sentiment (optional) | `PortfolioEngine` | In-process transformers model |

## Client (browser) state

| State | Persistence |
|-------|-------------|
| Portfolio, notes, assessments, alerts | None locally — always from API |
| `pda_synthesis_guidance` | `localStorage` (per browser) |
| Table sort, selected symbol, fib toggles, chart mode | JavaScript memory — lost on reload |

## Cloud deployment notes

- **Single-tenant DB**: all users of one deployed instance share one SQLite file (no auth layer yet).
- **Sleep vs data loss**: Render free tier sleeps when idle; waking does not clear the DB. **Redeploy** without a persistent disk can wipe `data/portfolio.db`.
- **LLM secrets**: `OPENAI_API_KEY`, `GEMINI_API_KEY`, etc. live in platform env vars only.
- **Re-import after redeploy**: if no persistent disk, keep analyst export files locally to restore state.

## Quick reference: durable vs ephemeral

**Survives restart** (if DB file exists): symbols, thresholds, holdings, notes, syntheses, assessments, alerts, TA trends/fibs, last-synced prices.

**Refreshed on schedule**: `current_price`, `analyst_target_1y` (every sync).

**Always live**: valuation ratios, auto fibs, chart series, screening scores, overview YTD.

**Never stored**: original import file blob.
