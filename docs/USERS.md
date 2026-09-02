# Adding users (Web & Mobile)

How to grant access for a new person. Users are **not** created by hand in SQL for normal
sign-in — the app upserts a `users` row on first successful Google login
(`get_or_create_user` in `db/database.py`).

When Google OAuth is enabled, each account gets an **isolated portfolio** in the same
Postgres database. Shared market data (prices, fundamentals, base assessments) is
deduplicated across users.

---

## 1) Web app

### Prerequisites

- `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET` set (local `.env` or Render).
- `OAUTH_REDIRECT_URI` registered exactly in [Google Cloud Console](https://console.cloud.google.com/apis/credentials) → OAuth client → Authorized redirect URIs.



### Steps

1. **Allowlist (if used)**
  If `ALLOWED_EMAILS` is set (comma-separated), add the person’s Google email and restart /
   redeploy the API so the new value is loaded.  
   Empty `ALLOWED_EMAILS` = any Google account may sign in (still subject to Google
   consent-screen rules below).
2. **Google OAuth “Testing” mode**
  If the OAuth consent screen is still in **Testing**, open Google Cloud Console →
   OAuth consent screen → **Test users** and add their Google email. Without this, Google
   will block the sign-in even if your app allowlist is correct.
3. **First sign-in**
  They open the web app → **Sign in with Google**. On success, a `users` row is created
   automatically with their own empty portfolio.
4. **Optional plan**
  Default `users.plan` is `free`. Until Stripe billing is live, the author can change a
   user’s tier in **Consol → Users · tier · symbols** (dropdown: Free / Standard / Pro).
   Only the account matching `AUTHOR_EMAIL` can open Consol.  
   You can also update `plan` in Postgres (`free` | `standard` | `pro`).  
   Do **not** set `USER_PLAN_OVERRIDE` on Render — that forces every user to one tier and
   ignores Consol assignments.



### Checklist (web)


| Check                                                 | Where                |
| ----------------------------------------------------- | -------------------- |
| Email on `ALLOWED_EMAILS` (if set)                    | Render env / `.env`  |
| Email under Google **Test users** (if app in Testing) | Google Cloud Console |
| Redirect URI matches `OAUTH_REDIRECT_URI`             | Google OAuth client  |
| They complete Sign in with Google once                | Browser              |


---



## 2) Mobile app (iOS) — per-user Google sign-in

Mobile uses **Google ID token → API session Bearer**, so each tester gets the **same isolation
as web** (their own `users` row / portfolio).

### How it works

1. App shows **Sign in with Google**.
2. Google returns an authorization code in the browser sheet; the app exchanges it for an
  **ID token** (on iOS the raw sheet result often has only `code` — exchange is required).
3. App `POST /auth/mobile/google` with `{ "idToken": "..." }`.
4. API verifies the token, upserts the user, stores a hashed session in `mobile_sessions`,
  returns `{ accessToken, user }`.
5. App sends `Authorization: Bearer <accessToken>` on API calls.
6. **Sign out** revokes that session (`POST /auth/mobile/logout`).

Shared `MOBILE_DEV_TOKEN` is **local/simulator only**. Do **not** bake it into TestFlight
production builds (removed from `mobile/eas.json` production env).

### Google Cloud setup (one-time)

1. [Google Cloud Console](https://console.cloud.google.com/apis/credentials) → create an
  **iOS** OAuth client with bundle ID `com.portfolio.dashboard`.
2. Keep (or create) the existing **Web** OAuth client used by the dashboard.
3. Put both client IDs where the API can accept them as ID-token audiences:
  - Render / `.env`: `GOOGLE_OAUTH_CLIENT_ID` (web) plus optional
   `GOOGLE_MOBILE_IOS_CLIENT_ID` / `GOOGLE_MOBILE_WEB_CLIENT_ID`
   (or comma-separated `GOOGLE_MOBILE_CLIENT_IDS`).
4. Put the same client IDs in the **mobile** build env (EAS secrets or `mobile/.env`):
  - `EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID`
  - `EXPO_PUBLIC_GOOGLE_WEB_CLIENT_ID` (often required so Expo can return an ID token)



### Steps to add a mobile tester

1. Add their Google email to `ALLOWED_EMAILS` (if used) and Google **Test users** (if OAuth
  app is in Testing) — same as web.
2. Invite them in **App Store Connect → TestFlight** (install access only; not defined in
  this repo).
3. They install via TestFlight → **Sign in with Google** → empty own portfolio.
4. Rebuild mobile after changing Google client IDs (`eas:testflight`).



### Checklist (mobile)


| Check                                                   | Where                    |
| ------------------------------------------------------- | ------------------------ |
| Email on `ALLOWED_EMAILS` + Google Test users           | Render / Google Console  |
| iOS + Web OAuth client IDs on API                       | Render env               |
| `EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID` / `WEB` in EAS build | Expo / `mobile/.env`     |
| No `EXPO_PUBLIC_MOBILE_DEV_TOKEN` on production builds  | `eas.json` / EAS secrets |
| TestFlight tester invite                                | App Store Connect        |




### Local simulator shortcut

For solo local work you may still set matching `MOBILE_DEV_TOKEN` /
`EXPO_PUBLIC_MOBILE_DEV_TOKEN` and optional `MOBILE_DEV_USER_EMAIL`. That binds the simulator
to **one** portfolio and must not be used for multi-tester TestFlight.

---



## Quick reference


| Client                       | How access is granted                                            | Portfolio isolation                                   |
| ---------------------------- | ---------------------------------------------------------------- | ----------------------------------------------------- |
| **Web**                      | Google sign-in (+ optional `ALLOWED_EMAILS` + Google Test users) | Yes — new `users` row on first login                  |
| **Mobile (TestFlight)**      | Google sign-in → per-user Bearer session                         | Yes — same `users` row as web for that Google account |
| **Mobile (local dev token)** | Shared `MOBILE_DEV_TOKEN`                                        | No — one bound user                                   |


---



## Related

- OAuth env vars: [README.md](../README.md)
- Mobile setup & TestFlight: [MOBILE.md](./MOBILE.md)
- `users` / `mobile_sessions` tables: [DATA.md](./DATA.md)
- Auth implementation: `auth.py`, `db/database.py`

