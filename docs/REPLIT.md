# Replit Mobile App — Integration Guide

Use this document when building a mobile client on Replit that talks to the Portfolio Dashboard Agent API.

## Architecture

```
┌─────────────────────┐         ┌──────────────────────────┐
│  Replit mobile app  │  HTTPS  │  Flask API (this repo)   │
│  (React Native/Expo)│ ──────► │  Deployed on Render      │
└─────────────────────┘         └──────────────────────────┘
                                           ▲
┌─────────────────────┐                    │
│  Web dashboard      │ ───────────────────┘
│  (browser)          │
└─────────────────────┘
```

The API is the product. Web and mobile are both clients.

Replit’s own mobile docs assume the backend runs on Replit (Database, server routes). **This project uses an external API on Render** — the Replit app is a thin client only. CORS is enabled on the API (`Access-Control-Allow-Origin: *`), so the mobile app can call Render directly.

Official Replit mobile workflow: [Native Mobile Apps](https://docs.replit.com/references/artifact-types/building-mobile-apps)

---

## Start on Replit

1. On the Replit home screen, describe your app and select **Mobile app** as the type.
2. Agent scaffolds a **React Native + Expo** project.
3. Preview with **Expo Go** (scan QR in the Project Editor) or an **iOS Simulator / Android Emulator** (Core/Pro/Enterprise plans).
4. Build and edit at **replit.com** — native mobile preview/submit is not available in the Replit iOS app.

For architecture validation you do **not** need App Store submission or an Apple Developer account. Expo Go is enough.

---

## Base URL & environment

Create a `.env` file in the Replit project root:

```
EXPO_PUBLIC_API_BASE_URL=https://your-app.onrender.com/api/v1
```

Expo inlines only `EXPO_PUBLIC_*` variables into the client bundle. Use that prefix so `process.env.EXPO_PUBLIC_API_BASE_URL` is available in app code.

You can also add the same key in **Replit → Tools → Secrets** for deployment, but the client still needs the `EXPO_PUBLIC_` prefix to receive it at runtime in Expo Go.

Never hardcode `localhost` in production builds. For local API dev on an Android emulator, the host machine is `10.0.2.2`, not `localhost`.

---

## Connectivity check

On launch, call `GET /health` before other screens. Render’s free tier **sleeps when idle** — the first request after sleep can take 5–15+ seconds. Show a loading/retry state instead of failing immediately.

```javascript
const API = process.env.EXPO_PUBLIC_API_BASE_URL;

async function api(path, options = {}) {
  const res = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

// Launch: wake API + read config
await api("/health");
const config = await api("/config");
```

---

## Essential endpoints for mobile v1

| Screen | Endpoints |
|--------|-----------|
| Launch | `GET /health`, `GET /config` |
| Home / Overview | `GET /overview` |
| Symbol list | `GET /portfolio` (preferred) or `GET /symbols` |
| Symbol detail | `GET /symbols/{symbol}/inspector` |
| Holdings | `GET /holdings` (also in inspector `positionMechanics`) |
| Notes | `GET/POST /symbols/{symbol}/notes` |
| Note synthesis | `POST /symbols/{symbol}/notes/synthesize` (before assess) |
| Alerts | `GET /alerts?status=active`, `POST /alerts/{id}/dismiss` |
| Screening | `GET /screen?minUpside=30` → `{ "results": [...] }` |
| Fib map | `GET /fib-proximity` → `{ "results": [...] }` |
| Assess | `POST /symbols/{symbol}/assess`, `GET /assessments` |
| Refresh prices | `POST /sync` |

**`/portfolio` vs `/symbols`:** both return `{ "symbols": [...] }`. Prefer `/portfolio` for full symbol objects (including notes). `/symbols` is a lighter list without embedded notes.

**Inspector** (`GET /symbols/{symbol}/inspector`) bundles screening score, recommendation, alerts, assessments, notes, fib blueprint, trend waves, and `positionMechanics` — use this for a symbol detail screen instead of many separate calls.

---

## Sample fetch (JavaScript)

```javascript
const API = process.env.EXPO_PUBLIC_API_BASE_URL;

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

// Screening (note wrapped response)
const { results: screenRows } = await api("/screen?minUpside=30");

// Add a note
await api("/symbols/AAPL/notes", {
  method: "POST",
  body: JSON.stringify({ date: "2026-06-05", source: "Mobile", text: "Watching Q3 earnings" }),
});
```

---

## Prompt for Replit Agent

Copy this when starting your Replit mobile project:

> Build a React Native (Expo) portfolio app that consumes a REST API at `EXPO_PUBLIC_API_BASE_URL` (no business logic in the client except UI state).
>
> On launch: `GET /health` (handle slow first response — API may be waking from sleep), then `GET /config`.
>
> Screens and endpoints:
> - Overview: `GET /overview`
> - Symbol list: `GET /portfolio`
> - Symbol detail: `GET /symbols/{symbol}/inspector` (includes screening, recommendation, holdings via `positionMechanics`, notes, alerts, fib)
> - Holdings: `GET /holdings`
> - Notes: `GET/POST /symbols/{symbol}/notes`
> - Note synthesis (before assess): `POST /symbols/{symbol}/notes/synthesize`
> - Alerts: `GET /alerts?status=active`, dismiss via `POST /alerts/{id}/dismiss`
> - Screening: `GET /screen?minUpside=30` — response is `{ "results": [...] }`
> - Fib proximity: `GET /fib-proximity` — response is `{ "results": [...] }`
> - Assess: `POST /symbols/{symbol}/assess`, history via `GET /assessments`
> - Sync prices: `POST /sync`
>
> Cache notes locally for offline drafts only; POST to API when online. Always show assessment `createdAt` and `provider`. Handle errors from `{ "error": "..." }` responses. The API has no auth — it is a personal instance-wide portfolio.

---

## Assessment provider

Check `GET /config` → `assessmentProvider`:

- `rules` — no API key needed, threshold-based logic
- `openai` / `gemini` — LLM-backed (configured on server)

`config` may also include `features.noteSynthesis`, `importVersion`, and `syncIntervalSeconds`. Mobile does not need LLM keys; synthesis and assessments run server-side.

**Workflow:** synthesize notes → then assess. Assessment merges stored note syntheses with alerts, screening, and thresholds.

---

## Security & operations

| Topic | Notes |
|-------|-------|
| **No API auth** | Any client with the URL can read/write the portfolio. Fine for personal validation; add auth before a public App Store release. |
| **Render sleep** | Free tier sleeps when idle. Retry `/health` with a visible “Connecting…” state. |
| **Data persistence** | SQLite on Render needs an attached disk + `DATABASE_PATH=/var/data/portfolio.db` (see `render.yaml`, `docs/DATA.md`). Without a disk, redeploy can wipe data. |
| **Secrets** | Never put OpenAI/Gemini keys in the mobile app. LLM runs on the server only. `EXPO_PUBLIC_API_BASE_URL` is not secret — it is embedded in the app bundle. |

---

## Full API reference

See [API.md](./API.md) or `GET /api/v1/openapi.json` on your deployed host.
