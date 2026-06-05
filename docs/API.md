# Portfolio Dashboard Agent — API Reference

Base URL: `https://your-host/api/v1` (local: `http://localhost:5001/api/v1`)

All responses are JSON. CORS is enabled for mobile and web clients.

## Quick start

```bash
curl https://your-host/api/v1/health
curl https://your-host/api/v1/config
curl https://your-host/api/v1/overview
```

OpenAPI spec: `GET /api/v1/openapi.json`

---

## Configuration

### `GET /config`

Runtime settings for clients (no secrets).

```json
{
  "version": "v1",
  "assessmentProvider": "rules",
  "assessmentMode": "auto",
  "llmConfigured": false,
  "syncIntervalSeconds": 300,
  "fibProximityPct": 1.0,
  "docs": { "api": "/docs/api", "replit": "/docs/replit", "openapi": "/api/v1/openapi.json" }
}
```

`assessmentProvider`: `rules` | `openai` | `gemini`

---

## Portfolio & symbols

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/symbols` | List all tracked symbols |
| GET | `/symbols/{symbol}` | Symbol + notes |
| POST | `/symbols` | Add symbol `{ "symbol": "AAPL" }` |
| PUT | `/symbols/{symbol}` | Update thresholds |
| DELETE | `/symbols/{symbol}` | Remove symbol |
| GET | `/portfolio` | Full portfolio with notes |

**Symbol fields:** `currentPrice`, `targetPrice`, `buyBelow`, `sellAbove`

---

## Holdings

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/holdings` | Positions with market value, weight %, unrealized gain |
| POST | `/holdings` | `{ "symbol": "AAPL", "quantity": 10, "costBasis": 150 }` |
| PUT | `/holdings/{symbol}` | Update position |
| DELETE | `/holdings/{symbol}` | Remove holding |

---

## Overview

### `GET /overview`

Portfolio KPIs: symbol count, holdings, total market value, cost basis, unrealized gain, active alerts, top holdings.

---

## Import

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/import` | JSON body (legacy analysis export format) |
| POST | `/import/file` | Multipart upload, field name `file` (.json, .csv, or .txt) |

Legacy route (still supported): `POST /api/state`

**TXT analysis format** (symbol blocks with key: value lines):

```
AAPL
Current Price: 170
Target Price: 250
Buy Below: 175
Sell Above: 220
Quantity: 10
Cost Basis: 150

MSFT
Current: 420
Target: 500
Shares: 5
```

JSON saved as `.txt` also works.

---

## Notes

| Method | Endpoint | Body |
|--------|----------|------|
| GET | `/symbols/{symbol}/notes` | — |
| POST | `/symbols/{symbol}/notes` | `{ "date": "2026-06-05", "source": "Earnings", "text": "..." }` |
| DELETE | `/symbols/{symbol}/notes/{id}` | — |

---

## Alerts

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/alerts?symbol=AAPL&status=active` | List alerts |
| POST | `/alerts/evaluate` | Sync prices + generate new alerts |
| POST | `/alerts/{id}/dismiss` | Dismiss alert |

**Alert types:** `buy_below`, `sell_above`, `fib_proximity`, `screener_upside`

---

## Screening & Fibonacci

| Method | Endpoint | Query params |
|--------|----------|--------------|
| GET | `/screen` | `minUpside`, `nearFib`, `belowBuy`, `hasAlerts`, `sort`, `order` |
| GET | `/fib-proximity` | — |
| GET | `/symbols/{symbol}/fib-levels` | — |
| GET | `/symbols/{symbol}/inspector` | Full context for one symbol |

---

## Assessments

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/symbols/{symbol}/assess` | Assess one symbol |
| POST | `/assess` | Assess all or `{ "symbols": ["AAPL", "MSFT"] }` |
| GET | `/assessments?symbol=AAPL&limit=10` | History |

**Response shape:**

```json
{
  "symbol": "AAPL",
  "action": "buy",
  "confidence": "high",
  "rationale": "...",
  "factors": ["..."],
  "provider": "rules",
  "createdAt": "2026-06-05 22:00:00"
}
```

**Actions:** `buy` | `sell` | `hold` | `watch`

---

## Sync

### `POST /sync`

Refreshes live prices via yfinance, evaluates alerts, returns updated state.

---

## Caching guidance (mobile clients)

| Data | Suggested cache | Notes |
|------|-----------------|-------|
| Prices | 30s–5min or always fetch | Stale prices break alerts |
| Notes, thresholds | Cache + push on edit | API is source of truth |
| Alerts | Fetch from API | Server generates them |
| Assessments | Cache until refresh | Show `createdAt` timestamp |
| Fib levels | Hours per symbol | Changes slowly |
| Overview | 1–5min | Aggregate of above |

**Rule:** Write changes via POST/PUT; never treat local cache as authoritative.

---

## Error format

```json
{ "error": "Human-readable message" }
```

HTTP status: `400` validation, `404` not found, `500` server error.
