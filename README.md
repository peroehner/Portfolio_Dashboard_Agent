# Portfolio Dashboard Agent

API-first portfolio screening, personal notes, alerts, holdings, and trade assessments. Built for local development in Cursor/VS Code with a path to Render deploy and future Replit mobile clients.

## Features

- **Portfolio** — symbols, buy/sell thresholds, live price sync (yfinance)
- **Notes** — personal notes per symbol, fed into assessments
- **Alerts** — buy-below, sell-above, screener upside, Fibonacci proximity
- **Holdings** — quantity, cost basis, weight %, unrealized gain
- **Screening** — multi-factor scored views + Fib proximity map
- **Inspector** — full single-stock context, chart patterns & trend waves
- **Assessment runs + Agent Reads** — rules engine (default) or optional OpenAI/Gemini
- **Import** — JSON/CSV analysis file upload

Learning to read the charts (patterns, `forming`/`confirmed` labels, trend
waves, technical stance): **[docs/PATTERNS.md](docs/PATTERNS.md)**.

Assessment signal scoring (SAI, patterns, confluence hit rates):
**[docs/signal_track_record.md](docs/signal_track_record.md)** (Agent Signal Record).

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
Import file / UI edits  →  REST API (session user_id)  →  Postgres
                              ↓
                    symbol_market (shared quotes)
                    symbols / holdings / … (per user)
                              ↓
                         yfinance (live quotes + on-demand enrichment)
```

When Google OAuth is enabled, each account has an isolated portfolio in the same database. Market data (prices, fundamentals, base assessments) is deduplicated across users.

### What is persisted (Postgres)

| Table | Scope | Contents |
|-------|-------|----------|
| `symbols` | Per user | Personal target, trade thresholds, annual dividend |
| `symbol_market` | Shared | Current price, day change, analyst targets, fundamentals JSON |
| `symbol_assessment` | Shared | One base LLM assessment per symbol per UTC day |
| `holdings` | Per user | Quantity, cost basis, purchase date, account |
| `notes` | Per user | Note text + LLM synthesis (JSON), provider, timestamps |
| `assessments` | Per user | Overlay assessment history (action, rationale, factors) |
| `alerts` | Per user | Threshold, Fib proximity, screener alerts (`active` / `dismissed`) |
| `symbol_technical` | Per user | TA import: time window, fib anchor, trend waves, fib levels (JSON) |

Deleting a symbol cascades to its notes, alerts, assessments, holdings, and technical snapshot for that user (`db/database.py`).

### Import behavior

- **Merge** (default): upserts symbols, holdings, and technical data; keeps existing notes, assessments, and alerts for symbols still in the portfolio.
- **Replace**: clears **your** symbols first (cascade wipe), then loads the file only.
- Notes are **not** imported from analyst files — only added via the UI/API.
- Import-time `currentPrice` / analyst hints are written to `symbol_market`, not `symbols`.

### Price sync

A background worker in `main.py` refreshes prices every **300 seconds** (`syncIntervalSeconds` in `/api/v1/config`). Manual **Sync Prices** does the same. Updates **`symbol_market`** (shared); per-user reads join that table. Prices are cached, not streamed live.

After sync, alerts run per user; once per UTC day the **daily assessment worker** pre-warms shared base assessments in `symbol_assessment`.

### Ephemeral (not in Postgres)

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

With OAuth configured, each signed-in user has an isolated portfolio in that database. API requests require a session cookie (`credentials: same-origin` in the dashboard).

## Deploy to Render

1. Push this repo to GitHub.
2. In [Render](https://render.com): **New → Blueprint** and connect the repo (uses `render.yaml`).
3. Or **New → Web Service** manually:
   - Build: `pip install -r requirements-deploy.txt`
   - Start: `gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120 main:app`
   - Health check: `/health`
4. Add env vars in Render dashboard (see checklist below).
5. The Blueprint provisions a managed Postgres and wires `DATABASE_URL` automatically. To migrate existing local data, run `python scripts/migrate_sqlite_to_postgres.py` against the new `DATABASE_URL`.

### Production checklist (multi-user)

| Variable | Required | Notes |
|----------|----------|-------|
| `DATABASE_URL` | Yes | Render Postgres internal URL |
| `SESSION_SECRET` | Yes | Long random string — signs session cookies |
| `GOOGLE_OAUTH_CLIENT_ID` | Yes (multi-user) | Google Cloud OAuth client |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Yes (multi-user) | |
| `OAUTH_REDIRECT_URI` | Yes (multi-user) | `https://<your-service>.onrender.com/auth/callback` — must match Google console |
| `SESSION_COOKIE_SECURE` | Yes on HTTPS | `1` on Render (set in `render.yaml`) |
| `ALLOWED_EMAILS` | Optional | Comma-separated sign-in allowlist; empty = any Google account |
| `GEMINI_API_KEY` / `OPENAI_API_KEY` | Optional | LLM assessments & note synthesis |
| `DEDUP_BASE_ASSESSMENT` | Default `1` | Shared daily base assessment |
| `DAILY_ASSESSMENT_WORKER` | Default `1` | Pre-warm `symbol_assessment` after sync |

Register the redirect URI in [Google Cloud Console](https://console.cloud.google.com/apis/credentials) → OAuth client → Authorized redirect URIs. If the app is in **Testing** mode, add each user email under Test users.

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
├── db/database.py       # Postgres schema + migrations
├── docs/                # API, data/persistence, Replit guides
└── render.yaml          # Render blueprint
```
