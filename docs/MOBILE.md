# Portfolio Dashboard Agent — Mobile (iOS)

Native iOS client in [`mobile/`](../mobile/). Expo + React Native, same Flask API as the web dashboard.

## Testing strategy

| Where | Device | API | Command |
|-------|--------|-----|---------|
| **Local** | iOS Simulator only | `localhost:5001` | `npm run ios:local` |
| **Render** | Real iPhone (Expo Go) | `*.onrender.com` | `npm run start:render` → scan QR |

Keep local dev simple (simulator + local API). Use Render for real-device testing without Wi‑Fi IP / firewall setup.

---

## v1 screens

| Tab | API | Purpose |
|-----|-----|---------|
| **Overview** | `GET /overview` | KPIs, top holdings, recent alerts |
| **Portfolio** | `GET /portfolio`, `GET /assessments/overview` | Symbol list with SAI badges |
| **News** | `GET /news-feed` | SAI changes + ranked news |
| **Alerts** | `GET /alerts`, `POST /alerts/{id}/dismiss` | Active alerts, dismiss |
| **Symbol** (stack) | `GET /symbols/{symbol}/inspector` | Price, position, thresholds, recommendation |

Comma-separated ticker filters work the same as the web app (`GH, ne` → GH and NET).

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

## iPhone + Render (one-time setup)

### 1. Deploy API to Render

Push `main` — Render auto-deploys if the repo is connected. Service name: `portfolio-dashboard-agent`.

### 2. Render environment variables

In [Render Dashboard](https://dashboard.render.com) → your web service → **Environment**, add:

| Key | Value |
|-----|-------|
| `MOBILE_DEV_TOKEN` | Same secret as below (e.g. `pda-render-mobile-dev`) |
| `MOBILE_DEV_USER_EMAIL` | Your Google sign-in email |

Use a **different** token than local dev if you prefer. Never expose this in the App Store build — replace with proper OAuth later.

Restart the Render service after saving.

### 3. Start Expo for iPhone

```bash
cd mobile
```

Set the token in `mobile/.env` to match Render (or export it when starting):

```bash
EXPO_PUBLIC_MOBILE_DEV_TOKEN=pda-render-mobile-dev
```

Then:

```bash
npm run start:render
```

Scan the QR code with your iPhone **Camera** → opens in **Expo Go**.

**First load** after Render sleep can take 15–30 seconds (the app retries automatically).

### 4. Confirm Render URL

Default script uses `https://portfolio-dashboard-agent.onrender.com`. If your service URL differs, edit `start:render` in `mobile/package.json`.

Quick check in iPhone Safari:

```
https://portfolio-dashboard-agent.onrender.com/health
```

---

## Auth note

When Google OAuth is enabled on the API, the mobile app uses `MOBILE_DEV_TOKEN` (Bearer header) for development. Matching vars:

| File | Variable |
|------|----------|
| repo `.env` (local) | `MOBILE_DEV_TOKEN` |
| Render dashboard | `MOBILE_DEV_TOKEN` |
| `mobile/.env` | `EXPO_PUBLIC_MOBILE_DEV_TOKEN` |

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
└── assets/              # App icon placeholders
```

---

## Next steps (v2+)

- Screening & Fib map tabs
- Simulation / tax-loss proposal
- Notes editor + assess actions
- Google OAuth in mobile (replace dev token)
- EAS Build → TestFlight

## API reference

See [API.md](./API.md). OpenAPI: `GET /api/v1/openapi.json`.

Legacy client guide: [REPLIT.md](./REPLIT.md).
