# Reading the Dashboard — Technical Signals & Chart Patterns

A field guide to the technical overlays you see in the **Inspector**, the badges
in the **Symbols** list and **Screening** table, and the **Signal Track Record**
on the Summary. It explains every label (including `forming` vs `confirmed`) and
how each value is computed.

> **Big caveat first.** Chart patterns are *probabilistic — one input among
> many*. They are deterministic geometric reads of recent price pivots, not
> predictions. Treat them as a structured way to spot setups, always alongside
> fundamentals, valuation, notes, and the assessment rationale.

All signals are computed from ~2 years of daily history (configurable via
`TECHNICAL_SIGNALS_PERIOD`) using an adaptive, volatility-scaled zig-zag to find
the swing pivots. No external TA import is required.

---

## 1. Status labels: `forming` vs `confirmed`

Every detected pattern carries a **status**:

| Status | Meaning |
|--------|---------|
| `forming` | The shape is in place, but price has **not yet broken the key level** in the pattern's direction. It's a *watch item*, not a trigger. |
| `confirmed` | Price has **broken through the key level** (the neckline / support / resistance) in the pattern's direction. The measured-move target becomes active. |

The break direction depends on the pattern (details in §5). Example: a **Double
Top** is `forming` while price is **above** its neckline, and only `confirmed`
once price closes **below** it. This is why a stock sitting near its highs can
show "Double Top · forming" without it being a sell signal yet.

---

## 2. Direction & color coding

| Direction | Color | Where you see it |
|-----------|-------|------------------|
| Bullish | Green | Badge `◆`, legend dot, track-record |
| Bearish | Red | Badge `◆`, legend dot, track-record |
| Neutral | Amber | Symmetrical triangle, on-chart markers |

**Symbols list / Screening badges** use short codes:

| Badge | Pattern |
|-------|---------|
| `H&S` | Head & Shoulders |
| `iH&S` | Inverse Head & Shoulders |
| `DT` | Double Top |
| `DB` | Double Bottom |
| `Asc△` | Ascending Triangle |
| `Desc△` | Descending Triangle |
| `Sym△` | Symmetrical Triangle |

Hover any badge to see the full name, direction, status, and confidence.

---

## 3. Confidence (the `%`)

A 0–1 score shown as a percent (e.g. *89%*). It rewards how *clean* the pattern
is — specifically how closely the two defining pivots match (the two tops of a
double top, the two shoulders of an H&S):

```
confidence = min(0.95, base + 0.35 × closeness)
```

- `base`: Head & Shoulders 0.60, Double Top/Bottom 0.55, Triangles 0.50
- `closeness`: 1.0 when the paired pivots are identical, decaying as they diverge
- Capped at 0.95 — the model never claims certainty

So a higher % means a more textbook shape, **not** a higher probability of
playing out.

---

## 4. Key level & target

Each pattern reports a **key level** and (for reversals) a **measured-move
target**:

- **Key level** — the line price must break to confirm. Labeled `neckline`
  (double tops/bottoms, H&S), `resistance` / `support` (triangles), or `apex`
  (symmetrical triangle).
- **Target** — the projected move *after* a confirmed break, equal to the
  pattern's height measured from the key level. Triangles don't report a target.

On the Inspector chart:

- **Large outlined diamonds** connected by a solid line = the pattern's defining
  pivots (e.g. Top → Neckline → Top).
- **Dashed horizontal line** = the key level (neckline / support / resistance).
- **Dotted horizontal line** = the measured-move target.

The same pattern is summarized above the chart ("Chart Patterns" panel) and in
the chart legend.

---

## 5. The patterns

Pivot roles are listed in order; `a`, `b` are the paired pivots, `mid`/`head`
the central one.

### Double Top — bearish
- **Shape:** Top → Neckline (trough) → Top, with both tops at a similar level.
- **Key level:** neckline = the trough **between** the two tops.
- **Confirms when:** price closes **below** the neckline.
- **Target:** `neckline − (top − neckline)` (one pattern-height below).
- **Reads as:** failed retest of resistance; momentum rolling over.

### Double Bottom — bullish
- **Shape:** Bottom → Neckline (peak) → Bottom, both bottoms similar.
- **Key level:** neckline = the peak **between** the two bottoms.
- **Confirms when:** price closes **above** the neckline.
- **Target:** `neckline + (neckline − bottom)`.
- **Reads as:** support holding twice; reversal up.

### Head & Shoulders — bearish
- **Shape:** Left Shoulder → Trough → **Head (higher)** → Trough → Right
  Shoulder, shoulders at a similar level.
- **Key level:** neckline = the average of the two troughs.
- **Confirms when:** price closes **below** the neckline.
- **Target:** `neckline − (head − neckline)`.
- **Reads as:** classic topping structure.

### Inverse Head & Shoulders — bullish
- **Shape:** the mirror — Left Shoulder → Peak → **Head (lower)** → Peak →
  Right Shoulder.
- **Key level:** neckline = average of the two peaks.
- **Confirms when:** price closes **above** the neckline.
- **Target:** `neckline + (neckline − head)`.
- **Reads as:** classic bottoming structure.

### Ascending Triangle — bullish
- **Shape:** flat highs (resistance touched **≥3×**) + rising lows.
- **Key level:** resistance = average of the highs.
- **Confirms when:** price closes **above** the highs.
- **Target:** not projected (no measured move).
- **Reads as:** buyers stepping up into a ceiling — breakout bias.

### Descending Triangle — bearish
- **Shape:** flat lows (support touched **≥3×**) + falling highs.
- **Key level:** support = average of the lows.
- **Confirms when:** price closes **below** the lows.
- **Reads as:** sellers pressing a floor — breakdown bias.

### Symmetrical Triangle — neutral
- **Shape:** falling highs **and** rising lows converging.
- **Key level:** apex = midpoint of the latest high/low.
- **Status:** always `forming` (direction unknown until it breaks either way).
- **Reads as:** coiling / compression; watch for the break direction.

> **Only one pattern per symbol is shown** — the most structurally complete read.
> H&S (5 pivots) outranks triangles (4) and doubles (3), and triangles require
> ≥3 touches on the flat side so they aren't confused with a 2-touch double.

---

## 6. Trend Waves (the colored legs)

Below the price line, the chart draws up to 6 **trend waves** — the dominant
zig-zag legs detected over the adaptive window:

- `T1 ↑ Low → Peak (Bullish)`, `T2 ↓ Peak → Low (Bearish)`, alternating.
- The window auto-sizes per symbol so relevant swings aren't cropped — that's
  why the start date under "Detected Trend Waves" varies by symbol.
- Source is labeled **computed** (derived here) or **import** (from a TA
  snapshot), and   the global "Computed trends" toggle forces computed everywhere.

---

## 7. Fibonacci Levels (the horizontal price lines)

Fibonacci levels turn a recent price range into a ladder of **support /
resistance lines** that traders watch for bounces, retests, and breakouts. We
anchor the ladder to the **swing high** and **swing low** of a lookback window
(default ~90 trading days, `FIB_LOOKBACK_PERIOD`) — deliberately shorter than the
~2y window used for patterns and trend waves, so the levels track the *current*
range rather than the multi-year one.

Each level sits a Fibonacci fraction of the way **down** from the high:

```
level price = swing_high − (swing_high − swing_low) × ratio
```

So **0% is the high** (top of the range) and **100% is the low** (bottom). A
"61.8% retracement" means price has given back 61.8% of the prior up-move.

| Level | Name | What it means |
|-------|------|---------------|
| **0%** | High | Top of the measured range — overhead resistance / the line a full recovery must reclaim. |
| **23.6%** | Retracement (shallow) | A minor pullback; strong trends often hold above it. |
| **38.2%** | Retracement | A healthy, moderate pullback; a common bounce zone in an uptrend. |
| **50%** | Center Line | Range midpoint (not a true Fib ratio, but widely watched). We treat it as the **bull/bear baseline** — above is constructive, below is cautious — and it drives the Technical Stance (§8). |
| **61.8%** | Golden Pocket | The "golden ratio" and the most-watched level. Holding it keeps the larger up-move intact; losing it opens the path back to the base. |
| **78.6%** | Retracement (deep) | The last line before a full give-back; a deep test of the move. |
| **100%** | Base | Bottom of the range — the floor / support. |

**On the Inspector chart** the levels are horizontal lines, color-coded:
**0% High** (purple), **38.2% Fib** (blue), **50% Center** (amber),
**61.8% Golden** (red), **100% Base** (grey). The 23.6% and 78.6% retracements
are still used for *proximity* (below) even though the chart keeps the drawn line
set uncluttered.

**In the Patterns & Tech Signals table**, the **Nearest Fib** column shows the
closest level to the current price, its kind, and its dollar value
(e.g. `61.8% · Golden Pocket · $158.38`). The closer price sits to a level, the
more likely a retest or breakout — which is exactly what the `Alert` stance
flags (§8).

> Levels are **recomputed as the window rolls**, so they drift over time. They
> are reference zones, not hard predictions — strongest when they line up with a
> pattern's key level or a trend-wave pivot.

---

## 8. Technical Risk Advisory (the "Stance")

The Inspector's **Technical Stance** is a quick read of where price sits versus
its Fibonacci structure (§7):

| Stance | Trigger |
|--------|---------|
| `Strong` | Price at/above the **50% center** Fib level (bullish baseline). |
| `Alert` | Within **2%** of the nearest Fib level — imminent retest/breakout. |
| `Cautious` | Below the 50% center level — wait for stabilization. |
| `Neutral` | No center level available; monitor key boundaries. |
| `Unknown` | Not enough technical data. |

---

## 9. Signal Track Record (Summary)

Every assessment captures its recommendation **and** any detected pattern as a
forward-looking "bet". Once the horizon elapses they're scored:

| Term | Meaning |
|------|---------|
| Horizon | Days after capture before scoring (`TRACK_RECORD_HORIZON_DAYS`, default 21). |
| Band | Dead-band; moves smaller than this count as neutral (`TRACK_RECORD_BAND_PCT`, default 2%). |
| Win / Loss | Forward move agreed / disagreed with the signal's direction beyond the band. |
| Neutral | Move inside the band, or a hold/watch (non-directional) signal. |
| Hit rate | `wins / (wins + losses)` — neutrals excluded. |

It's **measurement only** — past hit rates are reported but do not yet re-weight
future signals (auto-calibration is a planned next step).

---

## 10. Related config knobs

All optional; see [.env.example](../.env.example).

| Variable | Default | Effect |
|----------|---------|--------|
| `ASSESSMENT_PATTERNS` | `1` | Enable/disable pattern detection |
| `TECHNICAL_PATTERN_TOL_PCT` | `3` | How close pivots must be to count as "similar" |
| `TECHNICAL_SIGNALS_PERIOD` | `2y` | History pulled per symbol (patterns/trends) |
| `FIB_LOOKBACK_PERIOD` | `90d` | Window for the Fibonacci swing high/low |
| `TRACK_RECORD` | `1` | Capture/score signals |
| `TRACK_RECORD_HORIZON_DAYS` | `21` | Scoring horizon |
| `TRACK_RECORD_BAND_PCT` | `2.0` | Win/loss dead-band |

Implementation lives in `services/technical_signals_service.py` (detection),
`services/fib_service.py` (Fibonacci levels), `services/inspector_service.py`
(stance + chart wiring), and `services/track_record_service.py` (scoring).
