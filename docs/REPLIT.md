# Replit Mobile App — Integration Guide

Use this document when building a mobile client on Replit that talks to the Portfolio Dashboard Agent API.

## Architecture

```
┌─────────────────────┐         ┌──────────────────────────┐
│  Replit mobile app  │  HTTPS  │  Flask API (this repo)   │
│  (React Native etc) │ ──────► │  Deployed on Render      │
└─────────────────────┘         └──────────────────────────┘
                                           ▲
┌─────────────────────┐                    │
│  Web dashboard      │ ───────────────────┘
│  (browser)          │
└─────────────────────┘
```

The API is the product. Web and mobile are both clients.

## Base URL

Set in your Replit secrets / env:

```
API_BASE_URL=https://your-app.onrender.com/api/v1
```

Never hardcode localhost in production builds.

## Essential endpoints for mobile v1

| Screen | Endpoints |
|--------|-----------|
| Home / Overview | `GET /overview`, `GET /config` |
| Symbol list | `GET /symbols` or `GET /portfolio` |
| Symbol detail | `GET /symbols/{symbol}/inspector` |
| Notes | `GET/POST /symbols/{symbol}/notes` |
| Alerts | `GET /alerts`, `POST /alerts/{id}/dismiss` |
| Screening | `GET /screen?minUpside=30` |
| Fib map | `GET /fib-proximity` |
| Assess | `POST /symbols/{symbol}/assess`, `GET /assessments` |
| Refresh prices | `POST /sync` |

## Sample fetch (JavaScript)

```javascript
const API = process.env.API_BASE_URL;

async function api(path, options = {}) {
  const res = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

// Overview screen
const overview = await api("/overview");

// Add a note
await api("/symbols/AAPL/notes", {
  method: "POST",
  body: JSON.stringify({ date: "2026-06-05", source: "Mobile", text: "Watching Q3 earnings" }),
});
```

## Prompt for Replit Agent

Copy this when starting your Replit mobile project:

> Build a mobile portfolio app that consumes a REST API at `API_BASE_URL` (no business logic in the client except UI state).
>
> API docs: fetch `GET {API_BASE_URL}/config` on launch, then use:
> - Overview: `GET /overview`
> - Symbols: `GET /portfolio`
> - Detail: `GET /symbols/{symbol}/inspector`
> - Notes: `GET/POST /symbols/{symbol}/notes`
> - Alerts: `GET /alerts?status=active`
> - Assess: `POST /symbols/{symbol}/assess`
> - Sync: `POST /sync`
>
> Cache notes locally for offline drafts only; POST to API when online. Always show assessment `createdAt` and `provider`. Handle errors from `{ "error": "..." }` responses.

## Assessment provider

Check `GET /config` → `assessmentProvider`:

- `rules` — no API key needed, threshold-based logic
- `openai` / `gemini` — LLM-backed (configured on server)

Mobile does not need LLM keys; assessments run server-side.

## Full API reference

See [API.md](./API.md) or `GET /api/v1/openapi.json` on your deployed host.
