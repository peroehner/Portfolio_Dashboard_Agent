# Portfolio Dashboard Agent

API-first portfolio screening, personal notes, alerts, holdings, and trade assessments. Built for local development in Cursor/VS Code with a path to Render deploy and future Replit mobile clients.

## Features

- **Portfolio** — symbols, buy/sell thresholds, live price sync (yfinance)
- **Notes** — personal notes per symbol, fed into assessments
- **Alerts** — buy-below, sell-above, screener upside, Fibonacci proximity
- **Holdings** — quantity, cost basis, weight %, unrealized gain
- **Screening** — multi-factor scored views + Fib proximity map
- **Inspector** — full single-stock context
- **Assessments** — rules engine (default) or optional OpenAI/Gemini
- **Import** — JSON/CSV analysis file upload

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
| `DATABASE_PATH` | `data/portfolio.db` | SQLite path |
| `FIB_PROXIMITY_PCT` | `1.0` | Fib alert band (%) |

## API

- Health: `GET /health`
- API v1: `GET /api/v1/health`
- Config: `GET /api/v1/config`
- OpenAPI: `GET /api/v1/openapi.json`
- Docs: `GET /docs/api`, `GET /docs/replit`

Full reference: [docs/API.md](docs/API.md)

## Deploy to Render

1. Push this repo to GitHub.
2. In [Render](https://render.com): **New → Blueprint** and connect the repo (uses `render.yaml`).
3. Or **New → Web Service** manually:
   - Build: `pip install -r requirements-deploy.txt`
   - Start: `gunicorn --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120 main:app`
   - Health check: `/health`
4. Add env vars in Render dashboard (optional LLM keys, `ASSESSMENT_MODE`).
5. For persistent SQLite, attach a Render disk and set `DATABASE_PATH=/var/data/portfolio.db`.

**Note:** Free-tier instances sleep when idle. Data on ephemeral disk resets on redeploy unless you use a persistent disk.

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
├── docs/                # API + Replit guides
└── render.yaml          # Render blueprint
```
