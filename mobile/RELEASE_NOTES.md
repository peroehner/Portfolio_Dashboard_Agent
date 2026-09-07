# Portfolio Dashboard — Mobile Release Notes

**Build:** 1.0.0 (TestFlight)  
**Branch:** `main` (includes #29 Tech Bias + #33 Buy/Sell badges)

Merging to GitHub `main` does **not** update TestFlight by itself. Ship a new binary:

```bash
cd mobile
npm run eas:testflight
```

Then install the new build in TestFlight on the phone (Apple processing can take 5–20 minutes).

## Paste into App Store Connect / TestFlight “What to Test”

```
Portfolio Dashboard mobile update

• Portfolio: sticky TBias column next to SAI (Bull/LBull/Mix/LBear/Bear)
• Buy/Sell Plan: PROPOSED / QUALIFIED badges on candidates (like Tax & Trim)
• Buy/Sell Plan: removed repeated Conviction/Readiness/Execution lines
• Portfolio sorting: empty values stay at the bottom (asc/desc)
• Star filter is a toggle (* / +*) — no more *.*.* from repeated taps
• News & Changes cards: more left-side space, less early wrapping
• Holdings Entry date now includes the year
• Notes: red Del control on each note to delete
• Note save: longer timeout + verifies save after timeout to reduce duplicates
• Dark theme restored

Please verify Portfolio TBias, Buy/Sell badges, sorting, star toggle, Entry year, and note delete on a physical device.
```

## What’s new

### Portfolio
- Sticky **TBias** column next to SAI: stripped-down Tech Stance (Bull / LBull / Mix / LBear / Bear) from fused confluence (loads via `/fib-proximity` after the list).
- Sorting puts empty values at the **end** (not the top), including when sorting descending (e.g. PT Val).
- Star filter button is a **toggle**: tap adds/removes `*`; long-press adds/removes `+*`. No more `*.*.*` from repeated taps.

### Buy/Sell Plan
- Candidate cards show **PROPOSED** (budgeted) or **QUALIFIED** (passes gate, not funded yet), matching Tax & Trim markers.
- Dropped duplicated Conviction / Readiness / Execution lines; Prox + Sell Rank / SAI Score remain.

### News & Changes
- Change cards give more room on the left so headlines wrap less while unused right margin is reduced.

### Symbol detail
- Holdings **Entry** date now includes the **year** (e.g. Jan 15, 2025).
- Notes: each note has a red **Del** control (trash + label) to delete that note.
- Adding a note uses a longer timeout; if the request times out, the app checks whether the note actually saved before showing an error (fewer duplicate notes from retries).

### Theme
- Dark theme restored for Mobile (no unintended light/white schema).

## How to verify on device

1. Portfolio → look for **TBias** sticky column immediately right of SAI (may show `—` until fib-proximity returns).
2. Portfolio → Buy/Sell Plan → funded legs show **PROPOSED**; gate-only legs show **QUALIFIED**.
3. Portfolio → sort PT Val ↓ → empty (`—`) rows stay at the bottom.
4. Portfolio / News / Fundamentals / Alerts → tap star filter twice → filter toggles on/off (no repeated `*`).
5. News & Changes → expand Changes → headlines use more left width.
6. Open a holding (e.g. IBRX) → Holdings → Entry shows month, day, **and year**.
7. Symbol → Notes → tap **Del** on a note → note is removed after refresh.
8. About (**i**) → check **Mobile client** version/build matches the new TestFlight binary (not only API git commit).
