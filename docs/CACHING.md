# Loading & caching

How the web dashboard and mobile app load data, what is cached where, and why some screens (especially **News** and **Fundamentals**) can be slow.

Companion docs: [DATA.md](./DATA.md) (persistence), [auto_run_overview.md](./auto_run_overview.md) (timers & passive caches), [MOBILE.md](./MOBILE.md) (mobile client).

**Update this file** when changing view-cache TTLs, auto-refresh loaders, `/news-feed` / `/fundamentals` cost, or mobile `useApiQuery` / timeout behavior.

---

## Three layers

| Layer | What | Typical freshness |
|-------|------|-------------------|
| **Server schedule** | Background price sync → Postgres `symbol_market` | Every **5 min** (`background_sync_loop`). Sync uses the browser-impersonating Yahoo session (`YF_IMPERSONATE` / curl_cffi). When daily history lags the latest US session (common from datacenter IPs), Sync prefers newer `regularMarketPrice` / `regularMarketTime` from quoteSummary over the stale history bar. |
| **Server schedule** | Background enrichment warmer → Postgres `symbol_market` fundamentals + news | Every **5 min** by default (`background_enrichment_warmer_loop`). Warms a small chunk per cycle with pauses; **starred symbols first** when `symbols.is_starred` is set (synced from mobile/web). |
| **Server TTL caches** | Yahoo/Finnhub fundamentals, news, ticker info (in-process + optional DB blob) | **~6h / 1h / 15m** (env-tunable) |
| **Client memory** | Browser view caches; mobile React state | Web: **~60s** on some views; mobile: until remount / refresh |

Prices and holdings in Summary / Holdings / Portfolio come from the **database**. Fundamentals and news are **enriched on demand** from Yahoo/Finnhub and then cached server-side.

```
User / timer ──► Client (optional 60s cache)
                      │
                      ▼
                 Flask API
                      │
         ┌────────────┼────────────┐
         ▼            ▼            ▼
      Postgres    TtlCache     yfinance / Finnhub
    (prices,       (news 1h,     (on miss)
     holdings,     fund ~6h,
     assessments)  info 15m)
```

Passive server caches **never self-refresh**; they recompute only on the next request after TTL expiry. Details: [auto_run_overview.md § Server-side caches](./auto_run_overview.md#section-4--server-side-caches-clarification).

---

## Server TTLs (defaults)

| Cache | Default | Env / location |
|-------|---------|----------------|
| Price sync | 300s | `main.py` `background_sync_loop` sleep |
| Analyst targets (on sync) | ~every 12th cycle (~1h) | `TARGET_REFRESH_CYCLES` |
| Fundamentals (in-process / Finnhub blob) | 21600s (6h) | `FUNDAMENTALS_CACHE_TTL_SECONDS` |
| Fundamentals (Postgres `symbol_market.fundamentals_json`) | same order | `SYMBOL_MARKET_FUNDAMENTALS_TTL_SECONDS` |
| News (Postgres `symbol_market.news_json`) | 3600s (1h) | `SYMBOL_MARKET_NEWS_TTL_SECONDS` |
| News headlines (in-process) | 3600s (1h) | `NEWS_CACHE_TTL_SECONDS` |
| Yahoo ticker `.info` | 900s (15m) | `YFINANCE_INFO_CACHE_TTL_SECONDS` |
| 52W high/low from daily history | 900s | `FUNDAMENTALS_52W_HISTORY_TTL_SECONDS` |
| yfinance failure cooldown | 600s | `YFINANCE_FAILURE_COOLDOWN_SECONDS` |

---

## Web app (`dashboard.html`)

### Active triggers (explicit)

| Action | Endpoint | Effect |
|--------|----------|--------|
| **Sync Prices** | `POST /sync` | Live prices → DB, alerts; `invalidateViewCaches()`; reload current view |
| **Assess Portfolio** | `POST /assess` | AI reads for symbols → DB; refreshes assessment / changelog UI (not a full price refresh) |
| **Assess Symbol** | `POST /symbols/:symbol/assess` | Single-symbol AI read; reloads Target / Inspector for that symbol |
| **Add / save / delete symbol** | `POST/PUT/DELETE /symbols…` | Persists portfolio; often `invalidateViewCaches()` + reload Portfolio / Overview |

### Client timers

| Timer | Interval | Behavior |
|-------|----------|----------|
| Auto-refresh | **30s** (`AUTO_REFRESH_MS`) | Refetches **Summary** and **Holdings** (`/overview`). Screening **re-renders cached rows only** unless empty. **Not** applied to Fundamentals, Fib, Simulation, Inspector |
| View cache TTL | **60s** (`VIEW_CACHE_TTL_MS`) | Screening, Fib map, Simulation’s `ensureFundamentalsCache()` |
| Top news throttle | **5 min** (`TOPNEWS_REFRESH_MS`) | Caps Yahoo-heavy `/news-feed` while Summary auto-refreshes |

### Per-view loading

| View | Client behavior |
|------|-----------------|
| **Summary / Holdings** | Always hit `/overview` on tab open **and** every 30s auto-refresh (DB-backed prices) |
| **Screening** | 60s in-memory cache; invalidated on Sync / Add / delete |
| **Fib map** | 60s cache; same invalidation |
| **Simulation** | Uses Screening cache (60s) + `ensureFundamentalsCache()` (60s) |
| **Fundamentals tab** | **Always** calls `GET /fundamentals` on tab open — **no** 60s client TTL (by design for now). Server may still serve from ~6h cache |
| **Inspector** | Always fetches per symbol; news sentiment memoized for the **browser session** |

### Fundamentals note

Simulation reuses a short client TTL via `ensureFundamentalsCache()`. The Fundamentals **tab** does not — each open hits the API. A longer client TTL was considered for cost; left unchanged because server ~6h already covers Yahoo freshness and Sync/Add invalidation would be required for correctness. See discussion below.

---

## Mobile app (`mobile/`)

There is **no** client-side TTL like the web `VIEW_CACHE_TTL_MS`. `useApiQuery` fetches on mount, keeps data in React state, and refetches only when `refresh()` runs (pull-to-refresh, Retry, or an explicit focus hook).

| Tab | When it fetches | Notes |
|-----|-----------------|-------|
| **Summary** | Mount + pull-to-refresh | No refetch on tab return (tabs stay mounted) |
| **Portfolio** | Mount + **every tab focus** (`useFocusEffect`) + pull-to-refresh | Most aggressive — picks up threshold edits after Symbol detail |
| **Fundamentals** | Mount + pull-to-refresh | No focus refetch; freshness ≈ server ~6h cache until pull |
| **News & Changes** | Mount + pull-to-refresh | `GET /news-feed` — see cost below |
| **Alerts** | Mount + pull-to-refresh | DB-backed |

Every query runs `api.wake()` first (`/health`, up to 3 retries × 4s) so a cold Render instance can spin up.

Timeouts: default API **12s**; Fundamentals and News **45s** (`FUNDAMENTALS_TIMEOUT_MS`, `NEWS_FEED_TIMEOUT_MS`).

---

## Expensive paths: Fundamentals & News

### Background warmer (cache-first)

A daemon thread (`background_enrichment_warmer_loop` in `main.py`) paces fundamentals + news fetches in small chunks with pauses (`ENRICHMENT_WARM_*` env vars). Priority order:

1. **Starred** symbols (`symbols.is_starred`, synced from mobile via `PUT /starred-symbols`)
2. **Held** symbols (positive `holdings.quantity`)
3. Remaining watchlist tickers

User endpoints read **persisted** blobs first (`symbol_market.fundamentals_json`, `symbol_market.news_json`). Pass `?live=1` to force the old on-demand bulk fetch. When `ENRICHMENT_LIVE_FALLBACK=1` (default), symbols with no warm cache yet are still filled live on the first request.

### Fundamentals

`GET /fundamentals` serves warmed Postgres/in-process cache for all portfolio symbols. Mobile uses `?includeNews=0` so news is skipped on that tab.

### News & Changes (`GET /news-feed`)

1. Loads recommendation changes from Postgres (cheap)
2. Reads **cached** enrichment per symbol (no burst unless `?live=1` or cache miss with live fallback)
3. Runs **`score_and_rank`** (bulk price history) to rank headlines by market reaction

Mobile aborts at **45s** when live fallback must cold-fetch a large portfolio. After the warmer has cycled, opens are typically fast.

Web Summary throttles top news to ≤ every 5 minutes and often calls `/news-feed` with `skipChanges=1`.

---

## Client TTL on Fundamentals (decision)

| Pros | Cons |
|------|------|
| Fewer bulk enrichment round-trips on tab flip | Stale until TTL unless invalidated on Sync / Add |
| Aligns Fundamentals tab with Simulation’s 60s helper | Small win when server ~6h cache is already hot |
| Damps re-hammering during provider cooldown | Can look “fresh” while Yahoo data is hours old |

**Current choice:** leave Fundamentals **without** a client TTL on web and mobile. Prefer fixing News cost (news-only enrichment) if timeouts remain painful.

---

## Quick reference

| Concern | Web | Mobile |
|---------|-----|--------|
| Prices | DB; 5 min server sync + Sync button; Summary/Holdings poll 30s | DB; Portfolio refetches on focus; Summary on mount/refresh |
| Fundamentals tab | Always API on tab open | Mount + pull-to-refresh |
| Fundamentals client TTL | Simulation only (60s) | None |
| Fundamentals server TTL | ~6h (+ 52W/15m overlays) | Same |
| News | Throttled ≤5 min on Summary | Full `/news-feed` on mount; 45s timeout; Retry often OK |
| Screening / Fib | 60s browser cache | Not in mobile v1 |

---

## Files

| Area | Path |
|------|------|
| Background sync | `main.py` → `background_sync_loop` |
| News / fundamentals enrichment | `services/fundamentals_service.py`, `services/enrichment_warmer_service.py`, `api/v1.py` (`/fundamentals`, `/news-feed`, `/starred-symbols`) |
| Relevance ranking | `services/news_relevance_service.py` |
| Web timers & view caches | `dashboard.html` (`VIEW_CACHE_TTL_MS`, `AUTO_REFRESH_MS`, `TOPNEWS_REFRESH_MS`, `loadFundamentals`, `ensureFundamentalsCache`) |
| Mobile queries | `mobile/lib/useApiQuery.ts`, `mobile/lib/api.ts`, `mobile/app/(tabs)/*.tsx` |
