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
| `recommendation` | SAI action (`buy`, `sell`, `watch`, `hold`) | Agent Read produced by the assessment run (rules / LLM) | `buy` → bullish; `sell` → bearish; `watch`/`hold` → neutral |
| `pattern` | Pattern name (e.g. `Double Bottom`) | Technical pattern detection on that run | From pattern type (bullish / bearish) |
| `confluence` | `Bullish` or `Bearish` | Fused confluence bias on that run | Same as label |

**Skipped (not falsifiable or unreliable):**

- Patterns with Risk verdict `veto` or `stale`
- Confluence bias `Mixed` (no directional edge)
- Captures when entry price is missing

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

---

## Scoring rules

Configurable band: `TRACK_RECORD_BAND_PCT` (default **2.0**).

| Signal direction | Win | Loss | Neutral |
|------------------|-----|------|---------|
| **Bullish** | Return ≥ +band% | Return ≤ −band% | Inside ±band% |
| **Bearish** | Return ≤ −band% | Return ≥ +band% | Inside ±band% |
| **Neutral** (hold/watch) | — | — | Always neutral; move is stored but not win/loss |

Return % = `(eval_price − entry_price) / entry_price × 100` using the symbol's
current price when the bet matures (best-effort from the portfolio price map).

**Hit rate** = `wins / (wins + losses)` — neutrals excluded from the denominator.

**Avg return** = mean `return_pct` over all evaluated rows in the bucket (includes
neutrals in the average).

---

## Summary UI

**Location:** Portfolio → Summary → **Agent Signal Record**

**Header meta (example):** `±2% win/loss band · 150 awaiting 21-day horizon`

- **150** = count of `signal_outcomes` rows still within their per-bet horizon
  (`outcome IS NULL`), not symbol count or assessment count.
- Scoring is evaluated when Summary loads (not a background cron).

**When empty:** one status line (e.g. `No matured scores yet · 151 bets still within the 21-day per-bet horizon — scores appear as each matures`). Long-form explanation and scoring rules live behind the **?** help button.

**When populated:**

- Overall hit rate + evaluated / wins / losses / avg return
- Tables by signal label under **SAI actions**, **Chart patterns**, **Confluence bias**

Color bands (hit rate): green ≥ 60%, amber ≥ 40%, red below.

---

## Configuration

See [.env.example](../.env.example).

| Variable | Default | Effect |
|----------|---------|--------|
| `TRACK_RECORD` | `1` | `0` disables capture and scoring |
| `TRACK_RECORD_HORIZON_DAYS` | `21` | Days after capture before a bet is scored |
| `TRACK_RECORD_BAND_PCT` | `2.0` | Dead-band for win/loss vs neutral |

---

## Implementation

| Piece | File |
|-------|------|
| Capture on assess | `services/assessment_service.py` → `_capture_signal_outcomes` |
| Mature + score | `services/track_record_service.py` → `evaluate_due` |
| API | `GET /api/v1/track-record` |
| UI | `dashboard.html` → `loadTrackRecord` / `renderTrackRecord` |
| Storage | `signal_outcomes` in `db/database.py` |

Chart pattern detection, risk validation, and confluence fusion are documented in
[PATTERNS.md](PATTERNS.md). Assessment and SAI flow in
[assessment_recommendation_news.md](assessment_recommendation_news.md).

---

## Planned (not implemented)

- Auto-calibration: re-weighting future signals from historical hit rates
- Rolling report windows (e.g. last 90 days only)
- Export of signal outcomes
