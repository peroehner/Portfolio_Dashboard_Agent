# Agent Signal Record

The **Agent Signal Record** (Summary tab) scores how well the portfolio
agent's forward-looking calls played out after a fixed evaluation horizon. It is
**measurement only** — past hit rates are reported but do not yet re-weight future
assessments or SAI output.

---

## What is tracked?

Bets are **not** taken from the SAI changelog alone and are **not** a separate
"AI-only" ledger. They are captured **when an assessment run completes** for a
symbol (scheduled auto-assess, portfolio assess, or manual assess-symbol).

Each successful assessment can record **up to several independent bets** for
that symbol at that moment:

| Kind (`signal_outcomes.kind`) | Label | Source | Direction |
|-------------------------------|-------|--------|-----------|
| `recommendation` | SAI action (`buy`, `sell`, `watch`, `hold`) | Published Agent Read action (proposal band is authority when enabled) | `buy` → bullish; `sell` → bearish; `watch`/`hold` → neutral |
| `pattern` | Pattern name (e.g. `Double Bottom`) | Technical pattern detection on that run | From pattern type (bullish / bearish) |
| `confluence` | `Bullish` or `Bearish` | Fused confluence bias on that run | Same as label |

**Skipped (not falsifiable or unreliable):**

- Patterns with Risk verdict `veto` or `stale`
- Confluence bias `Mixed` (no directional edge)
- Captures when entry price is missing

**Not captured today** (even though the system produces them elsewhere): trade
and harvest alerts (beyond Fib), news/notes sentiment on the bet row, Technical
Stance as its own kind. See [Roadmap](#roadmap--design-not-implemented).

| Kind | Status |
|------|--------|
| `recommendation` | Captured with confidence / Fit total / band code (P1) |
| `pattern` | Captured |
| `confluence` | Captured |
| `fib` | Captured from `fib_proximity` alerts (P1) |

**Related but separate:** the **SAI Changes** feed (`recommendation_changelog`)
logs only when the discrete **action** changes vs the prior assessment. The
Signal Record captures a **forward bet at every assessment** (even when the
action is unchanged), plus patterns and confluence.

---

## Naming

| Name | Use |
|------|-----|
| **Agent Signal Record** | UI title — scope = all agent-derived signals, with assessment as the trigger |
| SAI / recommendation row | The `buy`/`sell`/… action inside the record |
| Bet / signal outcome | One row in `signal_outcomes` awaiting or after scoring |
| Episode (planned) | One continuous SAI action from open until opposing/material flip or horizon |

"AI bets" alone is too narrow (chart patterns and confluence are technical, not
LLM output). "Agent Signal Record" keeps SAI as the headline bucket while
including patterns and confluence.

---

## Lifecycle

```
Assessment run completes (per symbol)
        │
        ▼
_capture_signal_outcomes ──► INSERT signal_outcomes (outcome NULL)
        │                    entry_price = price at assessment time
        │                    eval_due_at = captured_at + horizon_days
        ▼
Wait TRACK_RECORD_HORIZON_DAYS (default 21 calendar days)
        │
        ▼
Summary loads GET /track-record ──► evaluate_due()
        │                            compare current price vs entry
        ▼
outcome = win | loss | neutral  (stored permanently)
        │
        ▼
Aggregated hit rate + avg return in UI
```

**Trigger wording:** say *"after an assessment run"* — most runs are
auto-triggered; manual Assess Portfolio / Assess Symbol uses the same capture
path.

---

## Horizon vs accumulation

Two different "21-day" ideas — do not confuse them:

| Concept | Behavior |
|---------|----------|
| **Evaluation horizon** (`TRACK_RECORD_HORIZON_DAYS`, default **21**) | Per-bet **wait** before that individual signal is scored. Each bet has its own `eval_due_at`. |
| **Report aggregation** | **Accumulates** — all scored bets (`outcome IS NOT NULL`) are included in hit-rate tables. There is **no** rolling "last 21 days only" window and **no** automatic expiry of old scores. |

**Pending dedup:** at most **one open (unscored) bet** per `(symbol, kind, label)`.
A new assessment for the same symbol does **not** open a second pending `buy`
bet for `AAPL`; the original clock keeps running until it scores.

After scoring, a **later** assessment can open a **new** bet for the same label
(the prior row is already decided).

**Important (historical):** `buy` and `sell` are different labels. Before episode
scoring, a flip while the prior action was still pending opened a **second
overlapping** bet. **P0 episode scoring** early-closes the prior recommendation
at the flip capture’s entry price (live on assess, and via
`reconcile_recommendation_episodes` for older rows when Summary loads).

---

## Scoring rules

Configurable band: `TRACK_RECORD_BAND_PCT` (default **2.0**).

| Signal direction | Win | Loss | Neutral |
|------------------|-----|------|---------|
| **Bullish** | Return ≥ +band% | Return ≤ −band% | Inside ±band% |
| **Bearish** | Return ≤ −band% | Return ≥ +band% | Inside ±band% |
| **Neutral** (hold/watch) | — | — | Always neutral; move is stored but not win/loss |

Return % = `(eval_price − entry_price) / entry_price × 100`.

**SAI recommendation episodes (P0 — implemented):**

- An open `recommendation` bet is an **episode** for that action.
- When a later assessment publishes a **different** action, the prior pending
  episode is early-closed at the new capture’s `entry_price` (T1→T2 window).
- Soft-close includes `buy`/`sell` → `watch`/`hold`.
- Same action reassessed: existing pending dedup keeps one open episode.
- If no flip before `eval_due_at`: score at horizon as before.
- **Backfill:** `get_summary` runs `reconcile_recommendation_episodes`, which
  walks recommendation rows per symbol and re-scores any earlier episode that
  has a later differently labeled capture (using that capture’s entry price).
  Already-scored overlapping horizons are rewritten when they disagree with the
  episode flip price.

Patterns and confluence still use the fixed per-bet horizon (no episode model).

**Hit** = unweighted `wins / (wins + losses)` — neutrals excluded.

**Price** (`avgReturn`) = mean `return_pct` over all evaluated rows in the bucket (includes
neutrals in the average). Sign is **raw** price move.

**Follow** (`avgReturnAdj`) = mean direction-adjusted return: bullish uses
`+return_pct`, bearish uses `−return_pct`, neutral contributes `0`. Positive Follow
means “following the call” would have helped on average.

**Bet Strength Hit** (`calibratedHitRate`, UI column: **Bet-S-Hit**): same decisive bets
as Hit (wins+losses only; neutrals ignored), but each bet is **weighted**:

```
weight = LabelWeight × (1 + Score/100)
```

| Piece | Meaning | Values |
|-------|---------|--------|
| **LabelWeight** | Published confidence Label | high=3, medium=2, low=1 (missing→1) |
| **Score** | Proposal **total** (State+Trigger+Fit), stored as `fit_total` | 0–100 (missing→ scale 1.0) |

```
Bet-S-Hit = Σ(weights on wins) / Σ(weights on wins+losses) × 100
```

**Naming gotcha:** DB/API field `fit_total` is the full **Score**, not the Fit pillar alone.

**Portfolio examples (live Screening chips):**

| Symbol | Conf · Score | Weight |
|--------|--------------|--------|
| LRCX | High · 83 | 3 × 1.83 = **5.49** |
| SRPT | Medium · 56 | 2 × 1.56 = **3.12** |
| DOCU | Medium · 40 | 2 × 1.40 = **2.80** |
| TTD | Low · 63 | 1 × 1.63 = **1.63** |

TTD’s Score (63) sits in the Medium band, but Label Low keeps its Bet-S-Hit weight small — so a TTD loss barely offsets an LRCX-strength win.

**Mini-book:** LRCX-like win (5.49) + TTD-like loss (1.63) + SRPT-like win (3.12) → Hit 2/3 = **66.7%**, Bet-S-Hit 8.61/10.24 ≈ **84%**.

When strength is missing, every weight is 1 → **Hit = Bet-S-Hit**. Patterns and confluence
do not store strength today, so those rows stay equal. Once SAI strength fills in, if
Bet-S-Hit ≫ Hit prefer stronger signals; if ≪ Hit stronger calls are underperforming.
Summary insight grades categories by Bet-S-Hit so confluence gaps (e.g. Bearish) surface.

**Label vs Score:** Confidence **Label** (SAI Conf) and proposal **Score** (SAI Score) are separate. Score can stay
in a higher band while Label is softened (stability / guardrails) — “Score may lag Label.”
Screening **Conf · Score** hover explains the pair; full model + cross-surface map:
[SIGNAL_SCORES.md](./SIGNAL_SCORES.md) · [PROPOSAL_FRAMEWORK.md — Label vs Score](./PROPOSAL_FRAMEWORK.md#label-vs-score-screening-conf--score).

**SAI strength metadata (P1 — implemented):** recommendation bets store
`confidence`, `fit_total`, and `band_code` at capture (from the published
proposal). Older rows are backfilled from `assessments` via `assessment_id` when
Summary loads. Summary exposes `byConfidence` in the UI. `byFitBand` remains in the API only (not rendered).

**Confluence band metadata:** confluence bets store `confluence_band`
(`lean` | `strong`), `confluence_score`, `agree_count`, `conflict_count`, and
`signal_strength` (strong/moderate/weak conviction) at capture. Direction label
stays Bullish/Bearish for scoring continuity. Summary exposes
`byConfluenceBand` and `byConfluenceConflict` (`clean` = 0 conflicts,
`contested` = any). Older confluence rows lack these fields until new assesses.

**Fib bets (P1 — implemented):** when a new `fib_proximity` alert is inserted,
a `kind=fib` bet opens (label e.g. `61.8% Golden Pocket`). Direction: price
**above** level → bullish bounce hypothesis; **below** → bearish. Scored with the
same ±band / horizon rules (bounce vs break expressed as directional return).

**How to read “good” (early validation, not a market oracle):**

| Bar | Decisive hit rate | Notes |
|-----|-------------------|--------|
| Noise / no clear edge | ~45–55% | ±2% dead band + trending markets |
| Worth watching | ≥55% with N ≥ ~30 | Prefer stable across a rolling window |
| Actionable | ≥60% with larger N | Survive reset / window after model changes |

UI colors (green ≥ 60%, amber ≥ 40%) are display thresholds, not proven edge bars.

---

## Summary UI

**Location:** Portfolio → Summary → **Agent Signal Record**

**Header meta (example):** `±2% win/loss band · 150 awaiting 21-day horizon`

- **150** = count of `signal_outcomes` rows still within their per-bet horizon
  (`outcome IS NULL`), not symbol count or assessment count.
- Scoring is evaluated when Summary loads (not a background cron): first
  reconcile SAI episodes, then score due horizons.

**When empty:** one status line (e.g. `No matured scores yet · 151 bets still within the 21-day per-bet horizon — scores appear as each matures`). Long-form explanation and scoring rules live behind the **?** help button.

**When populated:**

- Overall hit rate + evaluated / wins / losses / Price · Follow · Bet Strength Hit
- Tables: **SAI actions**, **SAI by confidence**, **Chart patterns**,
  **Fib levels**, **Confluence bias**
  (API still exposes `byFitBand`; it is **not** shown in the UI.)

Color bands (hit rate): green ≥ 60%, amber ≥ 40%, red below.

---

## Configuration

See [.env.example](../.env.example).

| Variable | Default | Effect |
|----------|---------|--------|
| `TRACK_RECORD` | `1` | `0` disables capture and scoring |
| `TRACK_RECORD_HORIZON_DAYS` | `21` | Days after capture before a bet is scored if no episode flip |
| `TRACK_RECORD_BAND_PCT` | `2.0` | Dead-band for win/loss vs neutral |
| `TRACK_RECORD_ERA_CUTOFF_DATE` | `2026-08-31` | **Reminder only** — planned date to drop pre-era rows (not enforced yet) |

### Deferred era cutoff (do not reset yet)

Episode scoring improves **existing** history in place (reconcile on Summary load).
**Do not** wipe `signal_outcomes` while rolling out P0–P1.

**Remembered cutoff:** on/after **2026-08-31**, cut off data older than the commit
that shipped episode scoring (and related P0/P1 changes), so learning is not
diluted by mixed pre/post measurement eras. Until then keep all rows and rely on
reconcile. Enforcement (SQL/API/env gate) is still TODO — date is documented in
code as `TRACK_RECORD_ERA_CUTOFF_DATE`.

---

## Implementation

| Piece | File |
|-------|------|
| Capture on assess | `services/assessment_service.py` → `_capture_signal_outcomes` |
| Early-close on action flip | `TrackRecordService.early_close_conflicting_recommendations` |
| Historical episode reconcile | `TrackRecordService.reconcile_recommendation_episodes` |
| Strength backfill | `TrackRecordService.backfill_recommendation_strength` |
| Fib capture from alerts | `AlertsService._capture_fib_signal_bet` → `capture_fib_proximity_bet` |
| Mature + score | `services/track_record_service.py` → `evaluate_due` |
| API | `GET /api/v1/track-record` |
| UI | `dashboard.html` → `loadTrackRecord` / `renderTrackRecord` |
| Storage | `signal_outcomes` (+ `confidence`, `fit_total`, `band_code`, `alert_id`) |
| Tests | `tests/test_track_record_episodes.py`, `tests/test_track_record_p1.py` |

Chart pattern detection, risk validation, and confluence fusion are documented in
[PATTERNS.md](PATTERNS.md). Assessment and SAI flow in
[assessment_recommendation_news.md](assessment_recommendation_news.md). Proposal
bands in [PROPOSAL_FRAMEWORK.md](PROPOSAL_FRAMEWORK.md). Alerts data model in
[DATA.md](DATA.md).

---

## Roadmap / design (not implemented)

Ordered by leverage. **P0 and P1 are implemented.**

### P0 — SAI episode windows — DONE

See [Scoring rules](#scoring-rules). Live early-close on assess + reconcile for
historical overlapping recommendation rows.

### P1 — Bet strength + Fib kind — DONE

Confidence / Fit / band on recommendation bets; `byConfidence` / `byFitBand`;
Follow + Bet Strength Hit; `kind=fib` from `fib_proximity` alerts.

### P2 — Selected alerts as bets

**Rule:** An alert is a track-record bet only with an explicit contract: entry,
claim/direction, horizon, win/loss rule.

| Alert family | Track as bet? | Notes |
|--------------|---------------|--------|
| `fib_proximity` | Done (P1 `kind=fib`) | Bounce hypothesis from side-of-level |
| `trade_below` / `trade_above` (+ near) | Optional | “After plan level, move in plan direction” |
| 1YT categories | Weak | Ongoing state / refresh loop |
| `tax_loss_candidate` / `winner_trim_candidate` / `harvest_imbalance` | Later | Attractiveness flags today — need a separate success definition (rebound, trim outcome, tax), not raw price alone |

Do not dump every alert into the ledger as a directional edge.

### P3 — Technical Stance: do not add as its own kind

Technical Stance (Fib advisory Strong/Alert/Cautious, and confluence-as-stance
on the Fib map) already influences confluence bias (captured) and proposal
Trigger → published action (captured). A dedicated stance row would mostly
triple-count the same technical view. Keep out of Signal Record unless a thin
diagnostic slice is needed later.

### Also planned (supporting)

| Item | Intent |
|------|--------|
| **Era cutoff (deferred)** | On/after **2026-08-31**, drop rows older than the P0 ship commit — **not now**; keep history while episode reconcile improves it |
| **Reset** | Optional full wipe only if cutoff is insufficient |
| **Rolling report window** | Filter aggregation (e.g. last 6 months) — separate from per-bet horizon |
| **Plain-language Summary** | Category rollups + short verdict sentences on the Summary panel |
| **Comparable category UI** | Same chrome for SAI / Patterns / Confluence / (future) Fib with category-level hit + weighted avg |
| **Min-N gates** | Before using track record to nudge proposals (`PROPOSAL_TRACK_RECORD_WEIGHTS`), require window + sample size |
| Auto-calibration | Re-weight future signals from historical hit rates (only after P1 + window/cutoff) |
| Export | Dump of signal outcomes for offline analysis |

### Explicit non-goals (for now)

- Treating harvest alerts as price bets without a tax/outcome contract
- Folding Fib labels into the Patterns kind
- Scoring Technical Stance as a fourth primary bet kind
- Wiping all signal history immediately on P0 ship (use deferred era cutoff instead)
- Using forever-accumulation hit rates to steer the live agent before cutoff/window + strength metadata
