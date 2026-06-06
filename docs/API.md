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

**Symbol fields:** `currentPrice`, `targetPrice` (personal — from import `Personal Target:` line or UI), `analystTarget1y` (analyst mean from `1Y Mean Target estimate:` or sync), `buyBelow`, `sellAbove`, `annualDividend`

---

## Holdings

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/holdings` | Positions with market value, weight %, unrealized gain, gain %, annual dividend |
| POST | `/holdings` | `{ "symbol": "AAPL", "quantity": 10, "costBasis": 150 }` |
| PUT | `/holdings/{symbol}` | Update position |
| DELETE | `/holdings/{symbol}` | Remove holding |

---

## Overview

### `GET /overview`

Portfolio KPIs: tracked symbols, open positions, watchlist-only count, total market value, cost basis, unrealized gain, unrealized gain %, total 1YT value, total 1YT upside %, total personal target value, total personal upside %, projected annual ROC (dividend + 1YT appreciation), total annual dividend, active alerts, and holdings table.

---

## Import

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/import` | JSON body; optional `?mode=merge` or `?mode=replace` |
| POST | `/import/file` | Multipart upload, field name `file`; form field `mode`: `merge` (default) or `replace` |

**Import modes**

| Mode | Behavior |
|------|----------|
| `merge` | Update existing symbols from file and add new ones; keep symbols not in file |
| `replace` | Delete all symbols first, then import only symbols from the file |

Legacy route (still supported): `POST /api/state`

**TXT analysis format** — Technical Analysis Export blocks:

```
[TECHNICAL ANALYSIS EXPORT: AAPL]
Current Price: 311.40 $
Personal Target: 350 $ (Upside: 12.4%)
1Y Mean Target estimate: 310.51 $ (Upside: -0.3%)
Purchased 2750.00 shares on 2008-02-19 @ 4.50 $
Estimate annual dividend income: 2,887.36 $
```

- `Personal Target:` → personal `targetPrice` (optional; otherwise set via UI)
- `1Y Mean Target estimate:` → `analystTarget1y`

Generic symbol blocks with key: value lines also work (`Personal Target`, `Target Price`, `Current Price`, etc.).

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
