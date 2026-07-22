# Portfolio Dashboard Agent — Mobile (iOS)

Native iOS client in [`mobile/`](../mobile/). Expo + React Native, same Flask API as the web dashboard.

## Testing strategy

| Where | Device | API | How |
|-------|--------|-----|-----|
| **Local** | iOS Simulator | `localhost:5001` | `npm run ios:local` |
| **Expo Go** | iPhone (home Wi‑Fi / tunnel) | Render | `npm start` → scan QR |
| **TestFlight** | iPhone anywhere | Render | EAS Build → TestFlight (no Mac needed) |

Use **TestFlight** when you are away from home. Expo Go still needs a Metro packager (Mac or tunnel).

---

## v1 screens

| Tab | API | Purpose |
|-----|-----|---------|
| **Summary** | `GET /overview` | KPIs, allocation chart, recent alerts |
| **Portfolio** | `GET /portfolio`, `GET /assessments/overview`, `GET /holdings` | Sortable holdings table with SAI |
| **Fundamentals** | `GET /fundamentals?includeNews=0` | Valuation/growth + health/analyst tables, 52W range |
| **News** | `GET /news-feed` | SAI changes + ranked news |
| **Alerts** | `GET /alerts`, `POST /alerts/{id}/dismiss` | Active alerts, dismiss |
| **Symbol** (stack) | `GET /symbols/{symbol}/inspector` | Price, position, thresholds, recommendation |

Comma-separated ticker filters work the same as the web app (`GH, ne` → GH and NET).

### Loading & caching (mobile)

There is **no** client TTL. `useApiQuery` keeps in-memory state until remount / pull-to-refresh / Retry.

| Tab | Refetch behavior |
|-----|------------------|
| **Portfolio** | Also refetches on **every tab focus** (so threshold edits from Symbol detail show up) |
| **Summary / Fundamentals / News / Alerts** | Fetch on first mount; switching tabs does **not** refetch |

Each load calls `api.wake()` first (cold Render). Fundamentals and News use a **45s** timeout.

**News timeouts:** `/news-feed` currently runs bulk fundamentals+news enrichment for the whole portfolio, then ranks headlines — same cost class as Fundamentals. A **Retry after a few seconds** usually succeeds once the API is awake and server caches are warm. Full map: [CACHING.md](./CACHING.md).

---

## Local setup (simulator)

```bash
# Terminal 1 — API
python3 main.py

# Terminal 2 — mobile
cd mobile
cp .env.example .env
npm install
npm run ios:local
```

`mobile/.env` defaults to localhost. Use **`ios:local`** so the simulator always hits your Mac API.

---

## iPhone + Render (Expo Go)

### 1. Deploy API to Render

Push `main` — Render auto-deploys if the repo is connected. Service name: `portfolio-dashboard-agent`.

### 2. Render environment variables

In [Render Dashboard](https://dashboard.render.com) → your web service → **Environment**, add:

| Key | Value |
|-----|-------|
| `MOBILE_DEV_TOKEN` | Same secret as below (e.g. `pda-render-mobile-dev`) |
| `MOBILE_DEV_USER_EMAIL` | Your Google sign-in email |

Use a **different** token than local dev if you prefer. Never expose this in a public App Store build — replace with proper OAuth later.

Restart the Render service after saving.

### 3. Start Expo for iPhone

```bash
cd mobile
npm start
```

Scan the QR code with your iPhone **Camera** → opens in **Expo Go**. The app auto-uses Render on a physical device (localhost only works in the simulator).

To force Render on every device: `npm run start:render`.

**First load** after Render sleep can take 15–30 seconds (the app retries automatically).

### 4. Confirm Render URL

Default script uses `https://portfolio-dashboard-agent.onrender.com`. If your service URL differs, edit `start:render` in `mobile/package.json` and the `env` blocks in `eas.json`.

Quick check in iPhone Safari:

```
https://portfolio-dashboard-agent.onrender.com/health
```

---

## TestFlight (EAS) — use the app away from home

Prerequisites:

- Active [Apple Developer Program](https://developer.apple.com/account) membership
- Free [Expo](https://expo.dev) account
- App Store Connect access for the same Apple team

### One-time setup

```bash
cd mobile
npm install

# 1. Log into Expo (browser / credentials prompt)
npx eas login

# 2. Link this folder to an Expo project (creates projectId in app.json)
npx eas init

# 3. Optional: confirm Apple credentials / certs will be managed by EAS
npx eas credentials
```

Confirm in [App Store Connect](https://appstoreconnect.apple.com):

1. Create app **Portfolio Dashboard** if it does not exist yet  
2. Bundle ID: `com.portfolio.dashboard` (must match `mobile/app.json`)  
3. Install **TestFlight** on your iPhone and accept the tester invite for your Apple ID

### Build + submit

```bash
cd mobile

# Build on Expo servers and upload to TestFlight in one step
npm run eas:testflight
```

Equivalent:

```bash
npx eas build --platform ios --profile production --auto-submit
```

The first run is interactive: Apple ID + 2FA, distribution certificate, provisioning profile, App Store Connect API key. EAS can create those for you.

After Apple finishes processing (often 5–20 minutes):

1. Open **TestFlight** on your iPhone  
2. Install **Portfolio Dashboard**  
3. Open the app — it talks to Render (`EXPO_PUBLIC_API_BASE_URL` is baked in via `eas.json`)

Later updates: bump is automatic (`autoIncrement` + remote version source). Re-run `npm run eas:testflight`.

### Profiles (`eas.json`)

| Profile | Use |
|---------|-----|
| `production` | TestFlight / App Store binary |
| `preview` | Internal ad-hoc install (device UDIDs registered) |
| `development` | Dev client / simulator |

Production builds bake Render API URL + the current mobile Bearer token. Replace the token with Google OAuth before any public App Store release.

---

## Auth note

When Google OAuth is enabled on the API, the mobile app uses `MOBILE_DEV_TOKEN` (Bearer header) for development. Matching vars:

| File | Variable |
|------|----------|
| repo `.env` (local) | `MOBILE_DEV_TOKEN` |
| Render dashboard | `MOBILE_DEV_TOKEN` |
| `mobile/.env` / `eas.json` | `EXPO_PUBLIC_MOBILE_DEV_TOKEN` |

Production App Store builds should use proper Google sign-in, not a dev token.

---

## Project layout

```
mobile/
├── app/                 # Expo Router screens
│   ├── (tabs)/          # Overview, Portfolio, News, Alerts
│   └── symbol/[symbol].tsx
├── components/          # Shared UI
├── lib/                 # API client, formatters, theme
├── eas.json             # EAS Build / Submit profiles
└── assets/              # App icon placeholders
```

---

## Next steps (v2+)

- Screening & Fib map tabs
- Simulation / tax-loss proposal
- Notes editor + assess actions
- Google OAuth in mobile (replace dev token)

## API reference

See [API.md](./API.md). OpenAPI: `GET /api/v1/openapi.json`.

Legacy client guide: [REPLIT.md](./REPLIT.md).
