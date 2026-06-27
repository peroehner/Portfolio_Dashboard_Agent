# Portfolio Dashboard Agent (PDA) — Abstract

**Portfolio Dashboard Agent is a personal, always-current decision-support cockpit for your individual portfolio.** It turns what used to be a cumbersome, time-consuming, and error-prone routine — manually pulling quotes, fundamentals, charts, and headlines from a dozen sources and reconciling them in ever-multiplying Excel tabs — into a single, live view that is comprehensive yet digestible, and available at your fingertips.

PDA starts from a deliberate premise: **finding new, promising stocks is rarely the hard part.** You already have a portfolio — or a watchlist of names you believe in. The real challenge is pursuing that progress over time and harvesting gains on time, easily and without it becoming a chore. What you typically lack is the *time* to monitor attentively and the *fluency* to interpret the many metrics that professionals rely on. Left unattended, positions tend to become *orphaned* — the diligence that preceded the initial purchase fades once attention moves on or time runs short. PDA is built to counter exactly that: by fusing accurate, continuously refreshed information into clear signals, it lowers the effort and raises the confidence required to **keep managing actively** — to revisit a thesis, recognize when conditions have changed, and trade on purpose rather than by neglect. The aim is not to decide for you, but to make timely, well-educated decisions the path of least resistance.

And because management is a loop, PDA **closes it**: as you act on what you see and trades take place, the portfolio is updated to reflect them accurately — holdings, cost basis, and targets — so the view always mirrors reality and the next decision starts from solid ground.

## How it works — sources confluenced into insight

PDA ingests and cross-references several independent data streams, then fuses ("confluences") them into coherent signals rather than leaving you to stitch them together:

- **Market data (yfinance):** live prices, daily and intraday history, 52-week ranges, analyst 1-year targets, year-to-date performance, and a market index (SPY) used as a baseline for relative comparisons.
- **Fundamentals (yfinance / optional Finnhub):** valuation and quality ratios — P/E, PEG, growth, margins, ROE — alongside dividends.
- **News (yfinance / optional Finnhub):** per-symbol headlines, scored for genuine relevance via an event-study model (a market-adjusted, volatility-standardized, volume-confirmed price reaction) so market-moving news surfaces above noise — at both a daily and a 30-minute intraday resolution.
- **Technical structure:** chart patterns (forming vs. confirmed), adaptive trend waves, Fibonacci levels and proximity, and volume analytics (relative volume, point of control / value area).
- **Your own inputs:** holdings and cost basis, personal price targets and thresholds, free-text notes, and optional technical-analysis imports.

On top of this data, a layer of cooperating analytical "agents" — pattern, trend, volume/risk, and a **confluence agent** that consolidates the technical signals into a single bias and score — validates evidence *before* anything reaches the language model. The result feeds rules-based or AI-assisted (OpenAI/Gemini) **assessments and recommendations**, with changes tracked over time and a screening view that ranks the whole book on multiple factors. Headline figures — market value, weighted day change, unrealized gain, dividend income, and projected returns against analyst and personal targets — are summarized at a glance, with the ability to drill into any single name in the Inspector.

## The philosophy

**PDA augments judgment; it never substitutes for it.** Its job is to make accurate data and well-defined, transparent algorithms continuously available — so positions stay actively tended rather than orphaned, and so the user, not a black box, makes the final call, with the reasoning visible in the very metrics shown on screen.

If you manage your own portfolio and have ever wished the diligence were less manual, the metrics less opaque, and your good intentions easier to act on, PDA is built for you — and worth a deeper look to make up your own mind.
