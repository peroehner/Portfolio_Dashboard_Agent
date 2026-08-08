# Trading Proposal Framework

Decision structure for cleaner, more stable trading proposals (SAI and Inspector).
**Slice 1** ships the schema and API fields; scoring and Portfolio Fit deepen in later iterations.
Primary consumers: web assess/inspector today; **mobile** via the same JSON later.

## Goals

- Separate **slow conviction** (State) from **fast timing** (Trigger) and **personal constraints** (Portfolio Fit).
- Reduce flip-flop via **stability** (confirmation, hysteresis, cooldown).
- Keep proposals **API-first** and additive — existing `action` / `confidence` / `rationale` stay authoritative until scores graduate.
- Hint extension points (dividend target, volatility appetite, etc.) without blocking v1.

## Score model (0–100)

| Pillar | Range | What it captures | Cadence |
|--------|-------|------------------|---------|
| **State** | 0–50 | Valuation, business health, analyst quality, note thesis | Slow |
| **Trigger** | 0–30 | Patterns, Fib/confluence, news reaction, alerts, hard thresholds | Fast |
| **Portfolio Fit** | 0–20 | Concentration, personal thresholds, tax/lot context, filter-set intent | Personal |

```
total = state + trigger + portfolioFit   # 0–100
```

Slice 1 computes **heuristic scaffold scores** from data already in assess/inspector context.
They explain structure; they do **not** yet override the overlay/LLM action.

### Suggested action bands (advisory now; authority later)

| Total | Bias |
|------:|------|
| ≥ 75 | Strong buy / size-up candidate |
| 60–74 | Buy / add |
| 45–59 | Watch / hold with catalysts |
| 30–44 | Hold / trim bias |
| < 30 | Sell / avoid |

Emitted on every proposal as `bandBias` (`advisory: true`). **Does not change SAI action** until Slice 4. v1 keeps `proposal.action` aligned with the assessment action (`authority: "assessment"`).

## Label vs Score (Screening Conf · Score)

Screening’s **Conf · Score** chip shows **two measures**, not one duplicated field:

| Measure | What it is | Role |
|---------|------------|------|
| **Label** (High / Medium / Low) | Published conviction | Bet-S-Hit weight factor (3 / 2 / 1) |
| **Score** (0–100) | State + Trigger + Fit | Continuous setup quality; scales Bet-S-Hit via `(1 + score/100)` |

**Base Label from Score alone:** ≥75 High, ≥45 Medium, else Low — then Label may be **softened one notch** (stability gate / unconfirmed flip, or warn/block vetoes). **Score does not drop with that soften**, so Score can **lag behind** a lower Label.

**Examples (not bugs):**

| Chip | Reading |
|------|---------|
| `High · 83` | Label matches score band; weight ≈ `3 × (1+83/100) = 5.49` |
| `Medium · 45` | Floor of Medium band; sorts above any Low when Conf · Score is sorted Label-first |
| `Low · 63` | Score alone → Medium, but Label Low after soften — **Score may lag Label**; hover lists stability/guardrail when known |

Hover (native title) stays compact: Label → Score (State·Trigger·Fit) → Bet-S-Hit weight → Drivers → lag hint only when Label &lt; score-implied band. Sort tip: Label first, then Score.

Agent Signal Record **Bet-S-Hit** uses the same pair: `confidence_weight × (1 + fit_total/100)` where `fit_total` is proposal Score total. See [signal_track_record.md](./signal_track_record.md).

## Pillar detail

### A) State (0–50)

Slow-moving quality of the name and thesis.

- Upside vs personal / analyst targets  
- Screening / fundamentals health (margins, growth, valuation flags)  
- Note synthesis thesis quality (when present)  
- Analyst coverage quality (targets, dispersion — later)

**Upside weight (current scaffold):** State takes screening `upsidePct` (analyst **1YT** when present, else **personal Target**) and maps positive upside into up to **+20** of State’s 0–50 (`upside/45 × 20`, capped). Example: ~25.6% upside → about **+11 State**. That is a large share of State, so ambitious targets (especially when personal Target is the only one) lift Score/band quickly even if Label is later softened. **Likely tune:** reduce this cap or split personal vs Street upside so State is less dominated by Target.

### B) Trigger (0–30)

Why *now* (or why not).

- Active alerts (Fib proximity, 1YT, trade thresholds)  
- Chart patterns / confluence / technical stance  
- News reaction / sentiment event study  
- Hard personal threshold crosses (`rule_hard_trigger`)

### C) Portfolio Fit (0–20)

Whether the trade belongs in *this* portfolio.

**v1 signals**

- Position weight / concentration  
- Distance to personal buy-below / sell-above  
- Unrealized gain/loss (tax-awareness hint only)  
- Held vs watchlist

**Roadmap — iterate without schema break**

Prefer additive fields under `proposal.fitExtensions` / preferences API rather than renumbering pillars:

| Extension | Intent |
|-----------|--------|
| `targetAnnualDividend` | Prefer names that help hit a portfolio income goal |
| `volatilityPreference` | Cap beta / drawdown appetite (“how volatile I want to go”) |
| `maxSingleNameWeightPct` | Soft/hard concentration ceiling |
| `sectorCapPct` | Sector / factor balance |
| `taxLotPreference` | Harvest vs defer; wash-sale awareness |
| `filterSetBias` | Boost symbols in the user’s current filter-set |
| `liquidityFloor` | Skip illiquid names for size |
| `holdingPeriodBias` | Swing vs long-term fit |

Document new keys in this file when implemented; bump `schemaVersion` only on breaking changes.

## Stability

Stop SAI from oscillating on noise.

| Mechanism | Behavior |
|-----------|----------|
| **Confirmation cycles** | Prefer N consecutive agreeing reads before upgrading action |
| **Hysteresis band** | Enter buy/sell at stricter score than exit |
| **Cooldown** | After a flip, suppress opposite flip for a short window |

Slice 1 **reports** recent action streak and a simple hysteresis hint; it does not yet gate the published action.

## Vetoes / invalidators

Hard blocks that can zero or cap a proposal regardless of score:

- Hard sell/buy threshold override (already authoritative in overlay)  
- Extreme concentration (scaffold warning)  
- Missing price / delisted (future)  
- User-defined do-not-trade list (future)

Emitted as `proposal.vetoes[]` with `{ code, message, severity }`.

## API shape

`schemaVersion: 1` — additive fields only thereafter.

```json
{
  "schemaVersion": 1,
  "action": "watch",
  "confidence": "medium",
  "authority": "assessment",
  "scores": {
    "state": 28,
    "trigger": 14,
    "portfolioFit": 11,
    "total": 53
  },
  "components": {
    "state": { "score": 28, "max": 50, "factors": ["…"] },
    "trigger": { "score": 14, "max": 30, "factors": ["…"] },
    "portfolioFit": { "score": 11, "max": 20, "factors": ["…"] }
  },
  "vetoes": [],
  "stability": {
    "sameActionStreak": 2,
    "confirmationRequired": 2,
    "confirmed": true,
    "hysteresisHint": null,
    "cooldownUntil": null
  },
  "fitExtensions": {
    "targetAnnualDividend": null,
    "volatilityPreference": null,
    "maxSingleNameWeightPct": null,
    "sectorCapPct": null,
    "taxLotPreference": null,
    "filterSetBias": null
  },
  "rationale": "…",
  "actionSource": "base_assessment+overlay",
  "computedAt": "2026-07-28T12:00:00Z"
}
```

### Surfaces (Slice 1)

| Surface | Field | Notes |
|---------|-------|-------|
| `POST /symbols/{symbol}/assess` (and portfolio assess) | `proposal` on each assessment | Also persisted in `assessments.trading_recommendation` as JSON |
| `GET /symbols/{symbol}/inspector` | `recommendation.proposal` | Built from latest assessment + live context when possible |
| `GET /symbols/{symbol}/proposal` | top-level `proposal` | Dedicated read for mobile / tooling |
| Overview / Summary tables | unchanged for SAI list | Avoid UI disruption |
| Summary → Portfolio Fit preferences | form under Agent Signal Record | Sets `GET/PATCH /preferences` |
| Inspector SAI card | compact State / Trigger / Fit bars | Web only for now |

Mobile compact card is deferred; API fields remain optional for later clients.

## Implementation map

| Piece | Location |
|-------|----------|
| Doc (this file) | `docs/PROPOSAL_FRAMEWORK.md` |
| Builder | `services/proposal_service.py` |
| Preferences | `services/preferences_service.py` + `users.preferences_json` |
| Assess attach + persist | `services/assessment_service.py` |
| Inspector attach | `services/inspector_service.py` → `recommendation.proposal` |
| Dedicated route | `api/v1.py` → `GET /symbols/<symbol>/proposal` |
| Prefs API | `api/v1.py` → `GET/PATCH /preferences` |
| Web scorecard + prefs form | `dashboard.html` |

## Iteration plan

1. **Slice 1** — schema, scaffold scores, API attachment  
2. **Slice 2** — State/Trigger weight tune + track-record soft scales; `PROPOSAL_STABILITY_GATE` (default off)  
3. **Slice 3** — Portfolio Fit preferences + web compact scorecard (mobile deferred)  
4. **Tune (no authority)** — valuation stretch in State; advisory `bandBias`; header total chip  
5. **Slice 4** — scores become co-authority or primary; bands drive action with vetoes  

### Tuning log (no authority)

| Change | Why |
|--------|-----|
| Soft State drag when price is above target | Stretched names (e.g. AAPL) were scoring upside as if still cheap |
| PEG ≥ 2.5 or trailing P/E ≥ 35 soft State −4/−5 | Valuation caution without flipping SAI |
| `bandBias` advisory field + scorecard note | Make documented bands usable as a second opinion |
| Header chip shows proposal total | Scores were easy to miss below the fold in Inspector |
| *(candidate)* Cap / split Target upside in State | Upside can add up to +20 State; ambitious personal/Street targets dominate Score — reconsider weight |

### Env flags (Slice 2)

| Variable | Default | Effect |
|----------|---------|--------|
| `PROPOSAL_TRACK_RECORD_WEIGHTS` | `1` | Soft-nudge State/Trigger from Agent Signal Record hit rates (≥8 decisive samples) |
| `PROPOSAL_STABILITY_GATE` | `0` | When `1`, unconfirmed flips publish prior `proposal.action` (SAI assessment action unchanged) |

## Related

- Assessment overlay: `services/assessment_overlay_service.py`  
- Signal track record: [signal_track_record.md](./signal_track_record.md)  
- API overview: [API.md](./API.md)  
- Mobile surfaces: [MOBILE.md](./MOBILE.md) (proposal card later)
