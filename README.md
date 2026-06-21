# Portfolio Dashboard Agent

API-first portfolio screening, personal notes, alerts, holdings, and trade assessments. Built for local development in Cursor/VS Code with a path to Render deploy and future Replit mobile clients.

## Features

- **Portfolio** — symbols, buy/sell thresholds, live price sync (yfinance)
- **Notes** — personal notes per symbol, fed into assessments
- **Alerts** — buy-below, sell-above, screener upside, Fibonacci proximity
- **Holdings** — quantity, cost basis, weight %, unrealized gain
- **Screening** — multi-factor scored views + Fib proximity map
- **Inspector** — full single-stock context, chart patterns & trend waves
- **Assessments** — rules engine (default) or optional OpenAI/Gemini
- **Import** — JSON/CSV analysis file upload

Learning to read the charts (patterns, `forming`/`confirmed` labels, trend
waves, technical stance, track record): **[docs/PATTERNS.md](docs/PATTERNS.md)**.

## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-deploy.txt   # lightweight, no torch
cp .env.example .env                   # optional
python3 main.py
```

Open `http://localhost:5001/` (macOS may use 5001+ if AirPlay blocks 5000).

Full local stack with transformers (optional):

```bash
pip install -r requirements.txt
```

## Environment variables

See [.env.example](.env.example). Key settings:

| Variable | Default | Purpose |
|----------|---------|---------|
| `PORT` | auto | Server port |
| `ASSESSMENT_MODE` | `auto` | `auto`, `rules`, `openai`, or `gemini` |
| `OPENAI_API_KEY` | — | Enable OpenAI assessments |
| `GEMINI_API_KEY` | — | Enable Gemini assessments |
| `SKIP_TRANSFORMERS` | — | Set `1` on deploy to skip torch |
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/portfolio` | Postgres connection string |
| `FIB_PROXIMITY_PCT` | `1.0` | Fib alert band (%) |

## API

- Health: `GET /health`
- API v1: `GET /api/v1/health`
- Config: `GET /api/v1/config`
- OpenAPI: `GET /api/v1/openapi.json`
- Docs: `GET /docs/api`, `GET /docs/replit`

Full reference: [docs/API.md](docs/API.md)

## Data & persistence

The server stores durable portfolio state in **Postgres** (via `DATABASE_URL`; psycopg3 + connection pool). Locally, start it with `docker compose up -d db`. The browser is a client: it loads and edits via the REST API. Uploaded analyst/import files are **parsed once** — the raw file is not kept on disk.

> **Maintenance:** When you change persistence (schema, import modes, sync behavior, or client-side storage), update this section and [docs/DATA.md](docs/DATA.md). Trigger files: `db/database.py`, `services/import_service.py`, `services/portfolio_service.py`, `main.py` (background sync), `dashboard.html` (`localStorage`).

Canonical detail: [docs/DATA.md](docs/DATA.md)

### Architecture

```
Import file / UI edits  →  REST API  →  SQLite (source of truth)
                              ↓
                         yfinance (live quotes + on-demand enrichment)
```

### What is persisted (SQLite)

| Table | Contents | Typical source |
|-------|----------|----------------|
| `symbols` | Current price, personal target, buy-below / sell-above, annual dividend, analyst 1Y target | Import, manual edits, background price sync |
| `holdings` | Quantity, cost basis, purchase date, account | Import, API |
| `notes` | Note text + LLM synthesis (JSON), provider, timestamps | UI / API |
| `assessments` | Action, confidence, rationale, factors, note synthesis snapshot | Assess Symbol runs |
| `alerts` | Threshold, Fib proximity, screener alerts (`active` / `dismissed`) | Auto-created during sync |
| `symbol_technical` | TA import: time window, fib anchor, trend waves, fib levels (JSON) | Portfolio-App TA export |

Deleting a symbol cascades to its notes, alerts, assessments, holdings, and technical snapshot (`db/database.py`).

### Import behavior

- **Merge** (default): upserts symbols, holdings, and technical data; keeps existing notes, assessments, and alerts for symbols still in the portfolio.
- **Replace**: clears all symbols first (cascade wipe), then loads the file only.
- Notes are **not** imported from analyst files — only added via the UI/API.

### Price sync

A background worker in `main.py` refreshes prices every **300 seconds** (`syncIntervalSeconds` in `/api/v1/config`). Manual **Sync Prices** does the same. Updates `symbols.current_price` and `symbols.analyst_target_1y` in SQLite. Prices are cached, not streamed live.

### Ephemeral (not in SQLite)

Recomputed or fetched per request — not written to the database:

| Data | Source |
|------|--------|
| Screening P-Score, upside %, flags | `ScreeningService` from DB fields + live Fib |
| Inspector valuation (P/E, PEG, revenue growth, op margin) | `yfinance` per inspector request |
| Auto Fib levels (no TA import) | `FibService` — 90d price history |
| Chart timeline & trend leg peaks | `yfinance` for import time window |
| Overview YTD performers | `yfinance` year-start prices |

Browser-only (lost on full page reload unless noted):

| State | Where |
|-------|-------|
| Selected symbol, table sort, chart mode, fib checkbox toggles | JavaScript in memory |
| Synthesis guidance textarea | `localStorage` key `pda_synthesis_guidance` (same browser) |

Server config (not in Postgres): LLM API keys, `NOTE_SYNTHESIS_GUIDANCE`, `ASSESSMENT_MODE` — set in `.env` or cloud env vars.

### Cloud (Render)

One managed Postgres database backs the instance, injected as `DATABASE_URL` via the blueprint (`render.yaml`). Managed Postgres survives restarts and redeploys (the `free` plan expires after 30 days — switch to `basic-256mb` for durable storage).

All API clients (web dashboard, future Replit app) share that single database. There is no per-browser server session — the portfolio is instance-wide (multi-user auth is the next phase).

## Deploy to Render

1. Push this repo to GitHub.
2. In [Render](https://render.com): **New → Blueprint** and connect the repo (uses `render.yaml`).
3. Or **New → Web Service** manually:
   - Build: `pip install -r requirements-deploy.txt`
   - Start: `gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120 main:app`
   - Health check: `/health`
4. Add env vars in Render dashboard (optional LLM keys, `ASSESSMENT_MODE`).
5. The Blueprint provisions a managed Postgres and wires `DATABASE_URL` automatically. To migrate existing local data, run `python scripts/migrate_sqlite_to_postgres.py` against the new `DATABASE_URL`.

**Note:** Free-tier web instances sleep when idle. Managed Postgres persists across redeploys (the `free` DB plan expires after 30 days).

## Mobile (Replit)

The API is designed for a future Replit mobile client. See [docs/REPLIT.md](docs/REPLIT.md) for integration instructions and an agent prompt.

## Project structure

```
├── main.py              # Flask app, background sync, deploy entry
├── engine.py            # yfinance + optional sentiment
├── dashboard.html       # Web UI
├── api/v1.py            # REST routes
├── services/            # Business logic
├── db/database.py       # SQLite schema
├── docs/                # API, data/persistence, Replit guides
└── render.yaml          # Render blueprint
```
