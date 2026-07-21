# Portfolio Dashboard — Mobile Release Notes

**Build:** 1.0.0 (TestFlight)  
**Branch:** `main` (includes mobile six-fixes)

## Paste into App Store Connect / TestFlight “What to Test”

```
Portfolio Dashboard mobile update

• Portfolio sorting: empty values stay at the bottom (asc/desc)
• Star filter is a toggle (* / +*) — no more *.*.* from repeated taps
• News & Changes cards: more left-side space, less early wrapping
• Holdings Entry date now includes the year
• Notes: red Del control on each note to delete
• Note save: longer timeout + verifies save after timeout to reduce duplicates
• Dark theme restored

Please verify sorting, star toggle, Entry year, note delete, and note save on a physical device.
```

## What’s new

### Portfolio
- Sorting puts empty values at the **end** (not the top), including when sorting descending (e.g. PT Val).
- Star filter button is a **toggle**: tap adds/removes `*`; long-press adds/removes `+*`. No more `*.*.*` from repeated taps.

### News & Changes
- Change cards give more room on the left so headlines wrap less while unused right margin is reduced.

### Symbol detail
- Holdings **Entry** date now includes the **year** (e.g. Jan 15, 2025).
- Notes: each note has a red **Del** control (trash + label) to delete that note.
- Adding a note uses a longer timeout; if the request times out, the app checks whether the note actually saved before showing an error (fewer duplicate notes from retries).

### Theme
- Dark theme restored for Mobile (no unintended light/white schema).

## How to verify on device

1. Portfolio → sort PT Val ↓ → empty (`—`) rows stay at the bottom.
2. Portfolio / News / Fundamentals / Alerts → tap star filter twice → filter toggles on/off (no repeated `*`).
3. News & Changes → expand Changes → headlines use more left width.
4. Open a holding (e.g. IBRX) → Holdings → Entry shows month, day, **and year**.
5. Symbol → Notes → tap **Del** on a note → note is removed after refresh.
6. Symbol → add a note → save completes without false timeout when the server is slow; avoid re-tapping Save if a timeout appears until the list refreshes.
