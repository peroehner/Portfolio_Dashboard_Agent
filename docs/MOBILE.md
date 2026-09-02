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
| **Portfolio** | `GET /portfolio`, `GET /assessments/overview` | Sortable holdings table with SAI |
| **Fundamentals** | `GET /fundamentals?includeNews=0` | Valuation/growth + health/analyst tables, 52W range |
| **News** | `GET /news-feed` | SAI changes + ranked news |
| **Alerts** | `GET /alerts`, `POST /alerts/{id}/dismiss` | Active alerts, dismiss |
| **Symbol** (stack) | `GET /symbols/{symbol}/inspector` | Price, position, thresholds, recommendation |

When OAuth is enabled on the API, the app shows **Sign in with Google** first; each user sees only their portfolio (same accounts as web). See [Auth](#auth-web-and-mobile--same-users) below.

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

## iPhone + Render (Expo Go)

### 1. Deploy API to Render

Push `main` — Render auto-deploys if the repo is connected. Service name: `portfolio-dashboard-agent`.

### 2. Render environment variables

In [Render Dashboard](https://dashboard.render.com) → your web service → **Environment**, add:

| Key | Value |
|-----|-------|
| `SESSION_SECRET` | Long random string (signs web sessions **and** mobile JWTs) |
| `GOOGLE_OAUTH_CLIENT_ID` | Web OAuth client (same as today) |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Web OAuth secret |
| `GOOGLE_OAUTH_IOS_CLIENT_ID` | **iOS OAuth client** for mobile (bundle `com.portfolio.dashboard`) |
| `ALLOWED_EMAILS` | Comma-separated Gmail addresses allowed to sign in (web **and** mobile) |
| `OAUTH_REDIRECT_URI` | Your Render callback, e.g. `https://portfolio-dashboard-agent.onrender.com/auth/callback` |
| `SESSION_COOKIE_SECURE` | `1` |

**Do not rely on `MOBILE_DEV_TOKEN` / `MOBILE_DEV_USER_EMAIL` for multi-user testing** — those impersonate a single portfolio. Mobile now uses Google Sign-In → per-user JWT (same user rows as web).

Restart the Render service after saving.

### 3. Google Cloud Console (mobile client)

1. [Google Cloud Console](https://console.cloud.google.com/apis/credentials) → **Create credentials** → **OAuth client ID** → **iOS**
2. Bundle ID: `com.portfolio.dashboard`
3. Copy the client ID → Render `GOOGLE_OAUTH_IOS_CLIENT_ID` **and** mobile `EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID`

Optional: if you use **Expo Go** on a physical device, also set `EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID` in `mobile/.env` to your **Web** OAuth client ID.

### 4. Mobile `.env` (Expo Go / local)

```bash
cd mobile
cp .env.example .env
```

| Key | Purpose |
|-----|---------|
| `EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID` | iOS OAuth client (required when API auth is on) |
| `EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID` | Optional — Expo Go / web client fallback |
| `EXPO_PUBLIC_API_BASE_URL` | Usually omitted (auto: simulator → localhost, device → Render) |

For **EAS / TestFlight**, set the same `EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID` in [EAS environment variables](https://expo.dev) or `eas.json` `env` for the build profile.

### 5. Start Expo for iPhone

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

## Auth (web and mobile — same users)

When Google OAuth is enabled on the API (`GOOGLE_OAUTH_CLIENT_*`), **each person signs in with their own Google account** and only sees their portfolio — on web (session cookie) and mobile (JWT Bearer).

| Surface | Mechanism |
|---------|-----------|
| **Web** | Google OAuth → Flask session |
| **Mobile** | Google Sign-In → `POST /api/v1/auth/google` with `idToken` → JWT stored in SecureStore |

`ALLOWED_EMAILS` on Render applies to **both** web and mobile.

### Mobile sign-in flow

1. App loads `/api/v1/config` → `authEnabled: true` → login screen
2. User taps **Sign in with Google** (native / system browser via `expo-auth-session`)
3. App sends Google `id_token` to the API
4. API verifies token, upserts `users` row (same as web callback), returns JWT
5. All API calls use `Authorization: Bearer <jwt>`

Sign out: delete the stored token (future UI) or reinstall the app; token expires after `MOBILE_JWT_TTL_SECONDS` (default 7 days).

### Legacy dev token (single user only)

For local debugging without Google UI, you may still set matching `MOBILE_DEV_TOKEN` (API) and `EXPO_PUBLIC_MOBILE_DEV_TOKEN` (mobile). That binds **one** email via `MOBILE_DEV_USER_EMAIL` — not suitable for multiple testers.

| File | Variable |
|------|----------|
| repo `.env` (local API) | `MOBILE_DEV_TOKEN`, `MOBILE_DEV_USER_EMAIL` |
| `mobile/.env` | `EXPO_PUBLIC_MOBILE_DEV_TOKEN` |

Production / TestFlight builds should use Google Sign-In, not the dev token.

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
- ~~Google OAuth in mobile (replace dev token)~~ — **done** (`POST /api/v1/auth/google` + login screen)

## API reference

See [API.md](./API.md). OpenAPI: `GET /api/v1/openapi.json`.

Legacy client guide: [REPLIT.md](./REPLIT.md).
