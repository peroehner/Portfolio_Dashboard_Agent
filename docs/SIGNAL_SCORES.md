# Scores & ranks (canonical map)

One page for every **named score / rank** in PDA — what it is, where it appears, and what it is *not*.

Live glossary (mobile Buy/Sell Plan tooltips): [`mobile/lib/signalGlossary.ts`](../mobile/lib/signalGlossary.ts).

---

## Quick map

| Name | Formula (short) | Used in | Not the same as |
|------|-----------------|---------|-----------------|
| **SAI Score** | State + Trigger + Fit → 0–100 | SAI Conf·Score chip, Fit Band, Bet-S-Hit scale, **Buy Plan** Score mode, web Sim **Buy Score** | Plan Attract / Sell Rank / Trim |
| **SAI Conf** | High ≥75 · Med ≥35 · else Low (may **soften**) | Conf chip, Bet-S-Hit **Label** weight (3/2/1) | Fit Band (raw; same cuts) |
| **Fit Band** | High ≥75 · Med ≥35 · else Low (**raw** Score) | Screening Fit chip, Agent Signal Record `byFitBand` | SAI Conf (softened Label) |
| **Proximity** | \|price − threshold\| / price × 100% | Buy/Sell Plan Prox mode, web Sim **Close %** | Scores |
| **Plan Attract** | P(proximity) + T(triggered) + S(size) ≈ 0–80 | Sell Plan breakdown (P/T/S) | SAI Score |
| **Plan Sell Rank** | 80 − Plan Attract | **Sell Plan** Score mode, web Sim **Sell Rank** | Trim Score |
| **Loss Score** | Residual loss vs cost after 1YT (0–50 curve) | Tax & Trim (losers) | Sell Rank |
| **Trim Score** | Exhaustion + 52W peak + weight + Intent | Tax & Trim (winners) | Sell Rank / Plan Attract |

---

## SAI (Screening / Inspector)

### SAI Score

Published setup quality from the trading proposal:

```
total = state (0–50) + trigger (0–30) + portfolioFit (0–20)   # 0–100
```

Full pillar detail and action bands: [PROPOSAL_FRAMEWORK.md](./PROPOSAL_FRAMEWORK.md).

**Upside driver:** State “Upside vs …” prefers analyst **1YT** when present, else personal **PT** (same as screening `upsidePct`). Hover Drivers spell this out as `Upside vs 1YT` / `Upside vs PT`.

### SAI Conf (Label)

| Band from Score alone | Label |
|----------------------:|-------|
| ≥ 75 | High |
| ≥ 35 | Medium |
| else | Low |

Label may be **softened one notch** (stability / vetoes). **Score does not drop** with that soften — so Conf and Score can disagree. Screening Conf·Score hover uses **published** Conviction (`proposal.confidence`), matching the chip and Bet-S-Hit weight.

### Fit Band

**Same cuts and names as Conf base**, on **raw** Score (**not** softened):

| Band | Score range |
|------|-------------|
| high | 75–100 |
| medium | 35–74 |
| low | 0–34 |

Hover: `Fit Band: HIGH (80: 75 - 100)`.

**Why both chips?** Conf = published (may soften); Fit Band = raw control. Comparing them isolates softening’s effect on recommendation / Bet-S-Hit quality. Action bands (Buy/Watch/Sell) use a separate threshold ladder and are unchanged.

### Bet-S-Hit (Agent Signal Record)

```
weight = LabelWeight × (1 + SAI Score/100)
```

| Label | Weight |
|-------|-------:|
| High | 3 |
| Medium | 2 |
| Low | 1 |

Details: [signal_track_record.md](./signal_track_record.md). DB field `fit_total` is the full **SAI Score**, not the Fit pillar alone.

### Portfolio Intent

Role chip (tactical / accumulate / core / …) with **role glyph + tone** (not a numeric score). Soft Fit nudge ±2; Tax & Trim harvest lean ±5. See [PROPOSAL_FRAMEWORK.md — Portfolio Intent](./PROPOSAL_FRAMEWORK.md#portfolio-intent).

---

## Buy / Sell Plan

Mobile-first workflow: **Buy Plan** and **Sell Plan** pools (qualification + sort). Code: [`mobile/app/trade-plan.tsx`](../mobile/app/trade-plan.tsx).

### Modes

| Mode | Buy Plan | Sell Plan |
|------|----------|-----------|
| **Proximity** | Gate / sort by distance to buy threshold | Gate / sort by distance to sell threshold |
| **Score** | Gate / sort by **SAI Score** (≥ threshold, default ~45, max 100) | Gate / sort by **Plan Sell Rank** (≤ threshold; lower = stronger) |

Mode toggle label on mobile: **SAI / Rank**.

### Plan Attract → Plan Sell Rank (sell legs only)

Per planned **sell** leg:

| Piece | Cap | Meaning |
|-------|----:|---------|
| **P** proximity | ~50 | `max(0, 50 − \|% from threshold\|)` |
| **T** triggered | 15 | Sell: price ≥ threshold; Buy legs use the symmetric rule for Attract math only |
| **S** size | 15 | Scales with leg cash (`min(15, cash/50k × 15)`) |

```
Plan Attract ≈ P + T + S          # ~0–80
Plan Sell Rank = 80 − Attract     # lower = closer / triggered / larger
```

**Buy Score mode does not use Attract** — it uses **SAI Score** (State+Trigger+Fit).

### Web Simulation (today)

Web has **no** dedicated Buy/Sell Plan panel (unlike Tax & Trim). Closest surface: **Simulation** with **Buys / Sells / Both** leg filters and **Close %** (Proximity).

| Legs filter | Columns |
|-------------|---------|
| **Both** | Buy @ ×Sh + Sell @ ×Sh + Close % (unchanged) |
| **Sells** | Sell @ ×Sh + **Sell Rank** (Plan Sell Rank); **Buy @ ×Sh removed** |
| **Buys** | Buy @ ×Sh + **Buy Score** (SAI Score); **Sell @ ×Sh removed** |

**Roadmap:** a dedicated **Buy & Sell** view (pools / gates like Tax & Trim and mobile Trade Plan) remains a next step.

---

## Tax & Trim

Separate harvest ranks — **not** planned-trade Sell Rank.

| Score | Thesis |
|-------|--------|
| **Loss Score** | Expected residual %-loss vs cost **after applying 1YT** from today. Higher residual → higher score. Slider filters the loss pool. |
| **Trim Score** | Realize gains now: thin 1YT/PT **headroom**, near **52W high**, heavy **weight**, sell-leaning plan + Portfolio Intent lean. |

In-app formulas: Simulation → Tax & Trim **?** help (`dashboard.html`). Intent lean (±5) is separate from plan-share `intentPts` (−10…+10) inside Trim Score.

---

## Naming gotchas

1. **Conf vs Fit Band** — same High/Medium/Low cuts on SAI Score; **only Conf softens**. Fit Band is the raw control.
2. **Sell Rank ≠ Trim Score** — planned-leg readiness vs winner-harvest rank.
3. **Buy Score (web/mobile Score mode) = SAI Score** — not Plan Attract.
4. **`fit_total` in track-record storage = SAI Score total**, not Portfolio Fit alone.

---

## Related

- [PROPOSAL_FRAMEWORK.md](./PROPOSAL_FRAMEWORK.md) — pillars, Conf vs Score, Intent, API shape  
- [signal_track_record.md](./signal_track_record.md) — Bet-S-Hit, Fit Band tables  
- [MOBILE.md](./MOBILE.md) — Trade Plan / SAI surfaces  
- [API.md](./API.md) — proposal / assessment fields  
