# Ticker filters & `@` segments

PDA keeps **one portfolio** — every symbol you track lives in that book, whether you hold shares or not. Named `@` filters let you **focus a sub-set of that book in the UI** without maintaining separate watchlists or duplicate portfolios.

## Intention

Broker apps and spreadsheets often push you toward multiple watchlists: “AI names,” “cyclicals,” “candidates,” each with its own list to maintain. PDA takes the opposite approach:

- **Add every name you care about once** to the portfolio (held or watch).
- Use **`@` segments** as lightweight, reusable views over that single book.
- Switch focus instantly across Hold, Screen, Fund, Tech, Target, Inspect, and Summary insights — same filter string, same saved names.

Segments are a **viewing and navigation aid**, not a second source of truth. They do not carve the book into isolated silos.

### Agents and analysis always cover the full book

Background sync, price refresh, alerts, assessments, screening scores, news ranking, technical signals, and other agent services run across **all symbols in your portfolio**, regardless of:

- which `@` segment (if any) is active in the filter box, or
- whether you currently hold shares (`Held` vs `Watch`).

Filtering only changes what tables and sidebars **show**. It never pauses monitoring or analysis for symbols outside the current view.

## Where it appears

| Surface | Shared filter? | Notes |
|---------|----------------|-------|
| **Hold** | Yes (`trackedTickerFilter`) | Category chips (All / Held / Large / …) × ticker filter × Set Filter |
| **Screen** | Yes | Category chips × ticker filter × Set Filter |
| **Fund** | Yes | Sub-tabs × ticker filter × Set Filter |
| **Tech (Patterns / Fib)** | Yes | Band / confirmed × ticker filter × Set Filter |
| **Target / Inspect** SYMBOLS sidebars | Yes | Same string; saved `@` chips on those sidebars |
| **Summary** news / SAI / alerts | Separate box | Same `@` syntax; independent string so insights can stay wide while tables are focused |
| **Mobile** Portfolio, Fundamentals, News, Alerts | Yes (persisted across tabs) | Same expand / match rules; star filters (`*` / `+*`) on mobile |

Web: typing in any shared filter box updates the others. Mobile: `usePersistedSymbolFilter` keeps one string across those tabs.

## Syntax

Filter boxes accept comma-separated terms (case-insensitive substring match on the ticker):

| Input | Meaning |
|-------|---------|
| `gh, ne` | Include symbols whose ticker contains `GH` **or** `NE` |
| `-intc` | Exclude matches for `INTC` (excludes win over includes) |
| `@CL` | Expand saved segment `@CL` to its stored match string |
| `@CL=AMZN,GOOG` then **Enter** | Save / overwrite segment `@CL`, then the field becomes `@CL` |
| `@CL!` | Delete segment `@CL` (confirm) |
| **Tab** | Autocomplete a trailing `@` prefix; on an exact name, expand to the match string |
| `*` / `+*` | Starred OR / AND — mobile (and server match helper); web star set is not wired yet |

While you type `@c`, suggestion chips list saved names that match (`@CL`, `@CY`, …). Click a chip to insert that `@NAME`.

Saved segments are **per user**, stored in preferences (`tickerSegments`), and available on web and mobile alike.

### Example workflow

1. Add all names of interest to the portfolio (no need for a second watchlist app).
2. Save thematic views, e.g. `@AI=NVDA,AVGO,AMD` and `@CL=AMZN,GOOG,MSFT`.
3. On Hold or Screen, type `@AI` (Tab / chip) to focus that slice for reading, sorting, or Set Filter.
4. Clear the filter or switch to `@CL` — agents have kept assessing and alerting on the full book the whole time.

## Implementation pointers

| Layer | Location |
|-------|----------|
| Match / expand / define | `services/ticker_segments.py` (tests: `tests/test_ticker_segments.py`) |
| Persist | `PreferencesService` → `users.preferences_json.tickerSegments` |
| API | `GET/PATCH /api/v1/preferences` (`tickerSegments`); `GET /api/v1/preferences/ticker-segments/export` |
| Web | `dashboard.html` — `trackedTickerFilter`, `symbolMatchesTickerFilter`, `@` suggestion hosts |
| Mobile | `mobile/lib/filters.ts`, `TickerFilterInput`, `TickerSegmentsContext` |

Related: [DATA.md](./DATA.md) (preferences), [MOBILE.md](./MOBILE.md), [API.md](./API.md).
