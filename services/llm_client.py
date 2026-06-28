import json
import logging
import os
import re
import ssl
import time
import urllib.error
import urllib.request
from typing import Any

import certifi


class LLMClient:
    VALID_ACTIONS = {"buy", "sell", "hold", "watch"}
    VALID_CONFIDENCE = {"high", "medium", "low"}
    VALID_SENTIMENT = {"bullish", "neutral", "bearish"}

    def __init__(self):
        self.mode = os.environ.get("ASSESSMENT_MODE", "auto").strip().lower()
        self.provider = os.environ.get("LLM_PROVIDER", "").strip().lower()
        self.gemini_api_key = os.environ.get("GEMINI_API_KEY", os.environ.get("GOOGLE_API_KEY", "")).strip()
        self.openai_api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        self.gemini_model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
        self.openai_model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        self.synthesis_guidance = os.environ.get("NOTE_SYNTHESIS_GUIDANCE", "").strip()

    def active_provider(self) -> str:
        if self.mode == "rules":
            return "rules"
        if self.mode == "openai" or self._should_use_openai():
            return "openai"
        if self.mode == "gemini" or self._should_use_gemini():
            return "gemini"
        return "rules"

    def synthesize_note(
        self, symbol: str, note: dict[str, Any], guidance: str | None = None
    ) -> dict[str, Any]:
        """Send one raw note + synthesis prompt to LLM; result is stored on the note."""
        text = (note.get("text") or "").strip()
        if not text:
            return self._empty_synthesis()

        provider = self.active_provider()
        if provider == "openai":
            try:
                return self._normalize_synthesis(
                    self._call_openai_note_synthesis(symbol, note, guidance), provider="openai"
                )
            except RuntimeError as exc:
                return self._fallback_synthesis(symbol, note, provider, exc)
        if provider == "gemini":
            try:
                return self._normalize_synthesis(
                    self._call_gemini_note_synthesis(symbol, note, guidance), provider="gemini"
                )
            except RuntimeError as exc:
                return self._fallback_synthesis(symbol, note, provider, exc)
        return self._normalize_synthesis(
            self._rule_based_note_synthesis(symbol, note), provider="rules"
        )

    def _fallback_synthesis(
        self, symbol: str, note: dict[str, Any], provider: str, exc: RuntimeError
    ) -> dict[str, Any]:
        """Use rules engine when LLM call fails (quota, SSL, network, etc.)."""
        logging.warning("LLM synthesis failed (%s), using rules fallback: %s", provider, exc)
        result = self._normalize_synthesis(
            self._rule_based_note_synthesis(symbol, note), provider="rules"
        )
        result["llmFallback"] = True
        result["llmError"] = str(exc)[:300]
        result["attemptedProvider"] = provider
        return result

    def aggregate_note_syntheses(
        self, symbol: str, syntheses: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Combine persisted per-note syntheses into one view for combined assessment."""
        valid = [item for item in syntheses if item and item.get("summary")]
        if not valid:
            return self._empty_synthesis()
        if len(valid) == 1:
            return valid[0]

        growth = []
        projections = []
        catalysts = []
        sentiments = []
        summaries = []
        for item in valid:
            summaries.append(item.get("summary", ""))
            growth.extend(item.get("growthTrajectory") or [])
            projections.extend(item.get("revenueProjections") or [])
            catalysts.extend(item.get("catalystsToWatch") or [])
            if item.get("sentiment"):
                sentiments.append(item["sentiment"])

        sentiment = "neutral"
        if sentiments:
            bullish = sentiments.count("bullish")
            bearish = sentiments.count("bearish")
            if bullish > bearish:
                sentiment = "bullish"
            elif bearish > bullish:
                sentiment = "bearish"

        return {
            "summary": " | ".join(summaries[:4]),
            "growthTrajectory": growth[:10],
            "revenueProjections": projections[:6],
            "catalystsToWatch": catalysts[:8],
            "sentiment": sentiment,
            "sourceNoteCount": len(valid),
            "provider": valid[0].get("provider", "mixed"),
        }

    @staticmethod
    def hard_trigger(context: dict[str, Any]) -> dict[str, Any] | None:
        """Deterministic, unambiguous threshold events that MUST drive the action,
        regardless of any LLM opinion.

        Mirrors the two high-confidence branches of ``_rule_based_assessment``:
        price at/above the user's sell-above level -> SELL; price at/below the
        buy-below level -> BUY. These are the ONLY actions treated as authoritative.
        Returns ``{action, confidence, reason}`` or ``None`` when nothing fired.

        TODO(stale-threshold guard): a deferred item will down-rank ``confidence``
        here when the crossed threshold looks stale (e.g. ``sell_above`` far below
        the live price, as with pre-split GOOGL levels). Slot that adjustment in at
        this single point so BOTH the rules-only and the LLM-nuanced paths inherit
        it automatically.
        """
        price = context.get("currentPrice")
        buy_below = context.get("buyBelow")
        sell_above = context.get("sellAbove")
        alert_types = {a.get("type") for a in (context.get("alerts") or [])}

        if "sell_above" in alert_types or (
            sell_above is not None and price is not None and price >= sell_above
        ):
            ref = f" ({sell_above})" if sell_above is not None else ""
            return {
                "action": "sell",
                "confidence": "high",
                "reason": f"price is at or above your sell-above threshold{ref}",
            }
        if "buy_below" in alert_types or (
            buy_below is not None and price is not None and price <= buy_below
        ):
            ref = f" ({buy_below})" if buy_below is not None else ""
            return {
                "action": "buy",
                "confidence": "high",
                "reason": f"price is at or below your buy-below threshold{ref}",
            }
        return None

    def generate_assessment(self, context: dict[str, Any]) -> dict[str, Any]:
        """Combined assessment from stored note syntheses + market/portfolio context.

        Architecture (TASK C — rules authoritative for hard triggers, LLM for
        nuance + explanation):

          * A HARD trigger (price crossed buy-below/sell-above) is decided
            deterministically by :meth:`hard_trigger`. When it fires, the final
            ACTION is the rules action and the LLM may NOT override it — the LLM is
            still called to write the rationale/nuance for that action (the trigger
            is passed into the prompt as a hard constraint so the prose stays
            coherent), but its action/confidence are discarded.
          * When NO hard trigger fired, the LLM owns the graded action + confidence
            + rationale exactly as before (valuation / technicals / news).
          * When no LLM key is available, the same code path yields a pure-rules
            assessment.

        Every result carries an additive ``actionSource`` field describing what drove
        the action: ``"rule_hard_trigger" | "llm" | "rules_fallback"``. (Additive only
        — the persisted row shape is unchanged; consumers that ignore it still work.)
        """
        note_syntheses = context.get("noteSyntheses") or []
        combined = self.aggregate_note_syntheses(context["symbol"], note_syntheses)
        context = {
            **context,
            "noteSynthesis": combined,
            "unsynthesizedNoteCount": context.get("unsynthesizedNoteCount", 0),
        }

        # Decide the unambiguous threshold event up front; this — not the LLM —
        # owns the action whenever it is present.
        hard = self.hard_trigger(context)

        provider = self.active_provider()
        if provider in ("openai", "gemini"):
            try:
                raw = (
                    self._call_openai_assessment(context, hard_trigger=hard)
                    if provider == "openai"
                    else self._call_gemini_assessment(context, hard_trigger=hard)
                )
                result = self._normalize_assessment(raw, provider=provider, combined=combined)
            except (RuntimeError, json.JSONDecodeError, KeyError, ValueError) as exc:
                # LLM failed -> deterministic rules fallback (still honours the hard trigger,
                # because _rule_based_assessment applies the same threshold branches first).
                result = self._fallback_assessment(context, combined, provider, exc)
                result["actionSource"] = "rule_hard_trigger" if hard else "rules_fallback"
                return result

            if hard is not None:
                # Enforce the deterministic action/confidence over whatever the LLM
                # returned; keep its rationale/factors as the explanation of conviction.
                result["action"] = hard["action"]
                result["confidence"] = hard["confidence"]
                result["actionSource"] = "rule_hard_trigger"
            else:
                result["actionSource"] = "llm"
            return result

        # No LLM available: pure rules, identical output shape to before.
        result = self._normalize_assessment(
            self._rule_based_assessment(context, combined), provider="rules", combined=combined
        )
        result["actionSource"] = "rule_hard_trigger" if hard else "rules_fallback"
        return result

    def _fallback_assessment(
        self,
        context: dict[str, Any],
        combined: dict[str, Any],
        provider: str,
        exc: Exception,
    ) -> dict[str, Any]:
        """Use rules engine when LLM assessment call fails."""
        logging.warning("LLM assessment failed (%s), using rules fallback: %s", provider, exc)
        result = self._normalize_assessment(
            self._rule_based_assessment(context, combined),
            provider="rules",
            combined=combined,
        )
        result["llmFallback"] = True
        result["llmError"] = str(exc)[:300]
        result["attemptedProvider"] = provider
        return result

    def _should_use_openai(self) -> bool:
        if self.mode == "rules":
            return False
        if self.mode == "openai":
            return bool(self.openai_api_key)
        if self.mode == "gemini":
            return False
        return self.provider == "openai" or (not self.provider and bool(self.openai_api_key))

    def _should_use_gemini(self) -> bool:
        if self.mode == "rules":
            return False
        if self.mode == "gemini":
            return bool(self.gemini_api_key)
        if self.mode == "openai":
            return False
        return self.provider == "gemini" or (not self.provider and bool(self.gemini_api_key))

    def _call_openai_note_synthesis(
        self, symbol: str, note: dict[str, Any], guidance: str | None = None
    ) -> dict[str, Any]:
        payload = {
            "model": self.openai_model,
            "messages": [
                {"role": "system", "content": self._synthesis_system_prompt(guidance)},
                {"role": "user", "content": self._synthesis_user_prompt(symbol, note)},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        response = self._post_json(
            "https://api.openai.com/v1/chat/completions",
            payload,
            headers={"Authorization": f"Bearer {self.openai_api_key}"},
        )
        return json.loads(response["choices"][0]["message"]["content"])

    def _call_gemini_note_synthesis(
        self, symbol: str, note: dict[str, Any], guidance: str | None = None
    ) -> dict[str, Any]:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.gemini_model}:generateContent?key={self.gemini_api_key}"
        )
        payload = {
            "contents": [{
                "parts": [{
                    "text": self._synthesis_system_prompt(guidance) + "\n\n" + self._synthesis_user_prompt(symbol, note),
                }],
            }],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        }
        response = self._post_json(url, payload)
        content = response["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(content)

    def _call_openai_assessment(
        self, context: dict[str, Any], hard_trigger: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        payload = {
            "model": self.openai_model,
            "messages": [
                {"role": "system", "content": self._assessment_system_prompt()},
                {"role": "user", "content": self._assessment_user_prompt(context, hard_trigger)},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        response = self._post_json(
            "https://api.openai.com/v1/chat/completions",
            payload,
            headers={"Authorization": f"Bearer {self.openai_api_key}"},
        )
        return json.loads(response["choices"][0]["message"]["content"])

    def _call_gemini_assessment(
        self, context: dict[str, Any], hard_trigger: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.gemini_model}:generateContent?key={self.gemini_api_key}"
        )
        payload = {
            "contents": [{
                "parts": [{
                    "text": self._assessment_system_prompt()
                    + "\n\n"
                    + self._assessment_user_prompt(context, hard_trigger),
                }],
            }],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        }
        response = self._post_json(url, payload)
        content = response["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(content)

    def _rule_based_note_synthesis(self, symbol: str, note: dict[str, Any]) -> dict[str, Any]:
        combined = note.get("text") or ""
        date_label = note.get("date") or note.get("note_date") or ""
        growth_trajectory = []
        for match in re.finditer(
            r"(\w+(?:\s+\w+){0,4}?)\s+(?:growth\s+)?(?:accelerated\s+to\s+|grew\s+to\s+|up\s+)?"
            r"(\d+(?:\.\d+)?)\s*%\s*(?:year-over-year|YoY|yoy|quarter-on-quarter|QoQ|qoq)?",
            combined,
            re.IGNORECASE,
        ):
            segment = match.group(1).strip()
            if len(segment) > 60:
                segment = segment[-60:]
            growth_trajectory.append({
                "metric": segment or "Revenue growth",
                "growth": f"{match.group(2)}%",
                "period": date_label or self._extract_period(combined, match.start()),
            })

        revenue_projections = []
        for match in re.finditer(
            r"\$(\d+(?:\.\d+)?)\s*(million|billion|M|B)\s*(?:annual\s+)?(?:run\s+rate|revenue|ARR)?"
            r"(?:\s+milestone)?(?:\s+by\s+(late\s+)?(20\d{2}|Q[1-4]\s*20\d{2}))?",
            combined,
            re.IGNORECASE,
        ):
            unit = match.group(2).lower()
            scale = "million" if unit in ("million", "m") else "billion"
            year_part = (match.group(4) or "").strip()
            late_prefix = (match.group(3) or "").strip()
            timeline = f"{late_prefix} {year_part}".strip() if year_part else "unspecified"
            revenue_projections.append({
                "target": f"${match.group(1)} {scale} run rate",
                "timeline": timeline,
                "segments": [],
            })

        catalysts = []
        quarters = sorted(set(re.findall(r"Q[1-4]\s*20\d{2}|Q[1-4]", combined, re.IGNORECASE)))
        growth_rates = [float(item["growth"].rstrip("%")) for item in growth_trajectory]
        if growth_rates:
            avg_growth = sum(growth_rates) / len(growth_rates)
            next_q = self._next_quarter(quarters[-1] if quarters else date_label)
            catalysts.append({
                "period": next_q,
                "metric": "Revenue / segment growth",
                "threshold": f"{max(25, round(avg_growth * 0.6))}%+ YoY",
                "significance": "Confirms growth trajectory described in this note",
            })

        sentiment = "neutral"
        bullish_words = ("accelerated", "momentum", "largest", "impressive", "expect continued", "high value")
        bearish_words = ("decline", "miss", "weak", "slowdown", "cut", "risk")
        lower = combined.lower()
        bullish_hits = sum(1 for word in bullish_words if word in lower)
        bearish_hits = sum(1 for word in bearish_words if word in lower)
        if bullish_hits > bearish_hits:
            sentiment = "bullish"
        elif bearish_hits > bullish_hits:
            sentiment = "bearish"

        summary_parts = []
        if growth_trajectory:
            top = growth_trajectory[0]
            summary_parts.append(f"{top['metric']} grew {top['growth']}")
        if revenue_projections:
            summary_parts.append(
                f"Targeting {revenue_projections[0]['target']} by {revenue_projections[0]['timeline']}"
            )
        summary = ". ".join(summary_parts) if summary_parts else "Note captured; no quantified growth extracted."

        return {
            "summary": summary,
            "growthTrajectory": growth_trajectory[:5],
            "revenueProjections": revenue_projections[:3],
            "catalystsToWatch": catalysts[:3],
            "sentiment": sentiment,
            "provider": "rules",
        }

    def _rule_based_assessment(
        self, context: dict[str, Any], combined: dict[str, Any]
    ) -> dict[str, Any]:
        price = context.get("currentPrice")
        buy_below = context.get("buyBelow")
        sell_above = context.get("sellAbove")
        target = context.get("targetPrice")
        analyst_target = context.get("analystTarget1y")
        alerts = context.get("alerts", [])
        screening = context.get("screening") or {}
        unsynthesized = context.get("unsynthesizedNoteCount", 0)

        action = "hold"
        confidence = "medium"
        factors = []

        if unsynthesized:
            factors.append(
                f"{unsynthesized} note(s) not yet synthesized — run Synthesize on notes to guide assessment."
            )

        alert_types = {alert["type"] for alert in alerts}
        if "sell_above" in alert_types or (sell_above is not None and price is not None and price >= sell_above):
            action = "sell"
            confidence = "high"
            factors.append("Price is at or above your sell-above threshold.")
        elif "buy_below" in alert_types or (buy_below is not None and price is not None and price <= buy_below):
            action = "buy"
            confidence = "high"
            factors.append("Price is at or below your buy-below threshold.")
        elif "fib_proximity" in alert_types:
            action = "watch"
            confidence = "medium"
            factors.append("Price is near a key Fibonacci level.")
        elif "screener_upside" in alert_types:
            action = "watch"
            confidence = "medium"
            factors.append("Stock screens with substantial upside to target.")

        if combined.get("growthTrajectory"):
            factors.append(f"Note synthesis: {combined['summary']}")
            for catalyst in combined.get("catalystsToWatch", [])[:2]:
                factors.append(
                    f"Watch {catalyst.get('period', 'upcoming')}: {catalyst.get('metric', 'growth')} "
                    f"({catalyst.get('threshold', '')})"
                )

        if combined.get("sentiment") == "bullish" and action == "hold":
            action = "watch"
            factors.append("Stored note synthesis describes bullish growth trajectory.")

        if target and price and target > price and action == "hold":
            upside = (target - price) / price * 100
            if upside > 30:
                action = "watch"
                factors.append(f"Personal target implies {upside:.1f}% upside.")

        if analyst_target and price and analyst_target > price and screening.get("upsidePct", 0) > 20:
            factors.append(f"Analyst 1Y target implies {screening['upsidePct']:.1f}% upside.")

        factors.extend(self._fundamentals_factors(context.get("fundamentals") or {}, price))
        factors.extend(self._technical_factors(context.get("technical") or {}))
        news = context.get("recentNews") or []
        if news:
            factors.append(f"{len(news)} recent headline(s) available — see news context.")

        rationale = (
            f"{context['symbol']} combined assessment from stored note syntheses, thresholds, and alerts. "
            + " ".join(factors or ["No major trigger; maintain current view."])
        )

        return {
            "action": action,
            "confidence": confidence,
            "rationale": rationale,
            "factors": factors or ["No active triggers."],
            "noteSynthesis": combined,
        }

    @staticmethod
    def _fundamentals_factors(fundamentals: dict[str, Any], price: float | None) -> list[str]:
        """Derive a few human-readable rule-based factors from fundamentals."""
        factors: list[str] = []
        if not fundamentals:
            return factors

        valuation = fundamentals.get("valuation") or {}
        growth = fundamentals.get("growthProfitability") or {}
        health = fundamentals.get("financialHealth") or {}
        price_range = fundamentals.get("priceRange") or {}

        fwd_pe = valuation.get("forwardPe")
        rev_growth = growth.get("revenueGrowth")
        if fwd_pe is not None and rev_growth is not None:
            growth_pct = rev_growth * 100
            if fwd_pe > 30 and growth_pct < 15:
                factors.append(
                    f"Rich valuation: forward P/E {fwd_pe:.0f} vs {growth_pct:.0f}% revenue growth."
                )
            elif fwd_pe < 20 and growth_pct > 15:
                factors.append(
                    f"Reasonable valuation: forward P/E {fwd_pe:.0f} on {growth_pct:.0f}% revenue growth."
                )

        d2e = health.get("debtToEquity")
        fcf = health.get("freeCashflow")
        if d2e is not None and d2e > 150 and fcf is not None and fcf < 0:
            factors.append(f"Balance-sheet risk: debt/equity {d2e:.0f} with negative free cash flow.")
        elif fcf is not None and fcf > 0 and d2e is not None and d2e < 80:
            factors.append("Healthy balance sheet: positive free cash flow, modest leverage.")

        high_52w = price_range.get("high52w")
        low_52w = price_range.get("low52w")
        if price and high_52w and low_52w and high_52w > low_52w:
            position = (price - low_52w) / (high_52w - low_52w) * 100
            if position >= 90:
                factors.append(f"Trading near 52-week high ({position:.0f}% of range).")
            elif position <= 15:
                factors.append(f"Trading near 52-week low ({position:.0f}% of range).")

        return factors

    @staticmethod
    def _technical_factors(technical: dict[str, Any]) -> list[str]:
        """Human-readable rule-based factors from computed technical signals."""
        factors: list[str] = []
        if not technical:
            return factors

        trend = technical.get("trend") or {}
        momentum = technical.get("momentum") or {}
        swing = technical.get("swing") or {}

        # Lead with the Confluence agent's fused verdict — it already weighs the
        # individual lenses, so it belongs at the top of the technical factors.
        confluence = technical.get("confluence") or {}
        bias = confluence.get("bias")
        if bias and bias != "Mixed":
            strength = confluence.get("strength") or ""
            agree = confluence.get("agreeCount")
            total = confluence.get("totalSignals")
            tally = f" ({agree}/{total} technical signals agree)" if agree is not None and total else ""
            factors.append(f"Confluence: {strength} {bias.lower()}{tally}.".replace("  ", " "))
            conflicts = confluence.get("conflicts") or []
            if conflicts:
                factors.append("Confluence conflict: " + "; ".join(conflicts[:2]) + ".")
        elif bias == "Mixed":
            factors.append("Confluence: mixed technical signals — no clear directional edge.")

        stack = trend.get("maStack")
        if stack == "bullish":
            factors.append("Uptrend: price above rising 20/50/200-day averages.")
        elif stack == "bearish":
            factors.append("Downtrend: price below falling 20/50/200-day averages.")

        cross = trend.get("crossState")
        if cross == "golden":
            factors.append("Golden cross: 50-day crossed above the 200-day average.")
        elif cross == "death":
            factors.append("Death cross: 50-day crossed below the 200-day average.")

        rsi = momentum.get("rsi14")
        zone = momentum.get("rsiZone")
        if rsi is not None and zone == "overbought":
            factors.append(f"Momentum stretched: RSI {rsi:.0f} (overbought).")
        elif rsi is not None and zone == "oversold":
            factors.append(f"Momentum washed out: RSI {rsi:.0f} (oversold).")

        frames = technical.get("timeframes") or []
        dirs = {f["window"]: f["direction"] for f in frames if "window" in f}
        if dirs.get("1Y") == "up" and dirs.get("1M") == "down":
            factors.append("Short-term pullback within a longer-term uptrend.")
        elif dirs.get("1Y") == "down" and dirs.get("1M") == "up":
            factors.append("Short-term bounce within a longer-term downtrend.")

        nearest = swing.get("nearestLevel") or {}
        if nearest.get("distancePct") is not None and nearest["distancePct"] <= 2:
            factors.append(
                f"Price at the {nearest.get('label')} Fibonacci level "
                f"({swing.get('source', 'computed')} anchor)."
            )

        for pattern in (technical.get("patterns") or [])[:2]:
            conf = pattern.get("confidence")
            conf_txt = f", confidence {conf:.0%}" if isinstance(conf, (int, float)) else ""
            target = pattern.get("target")
            target_txt = f", measured target ≈ ${target}" if target else ""
            factors.append(
                f"Chart pattern: {pattern.get('name')} "
                f"({pattern.get('type')}, {pattern.get('status')}{conf_txt}){target_txt}."
            )
        return factors

    def _synthesis_system_prompt(self, guidance: str | None = None) -> str:
        prompt = (
            "You are a financial analyst assistant. The user provides a raw personal investment note "
            "(earnings call excerpt, quarter review, CEO quote). Your job is to synthesize it into "
            "structured guidance the user can track over time. "
            "Respond only with JSON using keys: summary, growthTrajectory, revenueProjections, "
            "catalystsToWatch, sentiment. "
            "summary: one concise sentence capturing the growth thesis from THIS note. "
            "growthTrajectory: array of {metric, growth, period} — quantify segment growth where stated. "
            "revenueProjections: array of {target, timeline, segments} — revenue run-rate or milestones. "
            "catalystsToWatch: array of {period, metric, threshold, significance} — what to verify "
            "in future quarters (e.g. Q2 2026 security growth >= 25% YoY). "
            "sentiment: bullish | neutral | bearish."
        )
        extra = (guidance or self.synthesis_guidance or "").strip()
        if extra:
            prompt += f"\n\nUser synthesis guidance (follow these instructions):\n{extra}"
        return prompt

    def _synthesis_user_prompt(self, symbol: str, note: dict[str, Any]) -> str:
        return (
            f"Synthesize this personal note for {symbol}.\n\n"
            f"Date: {note.get('date') or note.get('note_date') or 'unspecified'}\n"
            f"Source: {note.get('source') or 'unspecified'}\n\n"
            f"Raw note:\n{note.get('text', '')}"
        )

    def _assessment_system_prompt(self) -> str:
        return (
            "You are a portfolio assistant. Produce a combined assessment by merging the user's "
            "STORED note syntheses (already structured — do not re-parse raw notes) with price "
            "thresholds, active alerts, Fibonacci levels, screening scores, holdings context, "
            "company FUNDAMENTALS (valuation, growth/profitability, financial health, analyst "
            "consensus, 52-week range), and RECENT NEWS headlines. "
            "Weigh valuation vs. growth: e.g. a high forward P/E is only a concern if revenue/"
            "earnings growth and margins do not support it; rising debt-to-equity with weak free "
            "cash flow is a risk flag; price far above the 200-day average or near the 52-week "
            "high tempers upside. Treat news headlines as sentiment signals, not facts to act on "
            "alone, and never fabricate news that is not in the provided list. "
            "When a 'technical' block is present, weigh it for timing and conviction: the "
            "multi-timeframe trend and returns (reconcile short-term vs long-term, e.g. a "
            "short-term pullback within a long-term uptrend), the moving-average stack and "
            "50/200-day cross (golden/death), RSI and MACD momentum (flag overbought/oversold "
            "extremes), ATR volatility, 52-week range position, and the swing/Fibonacci "
            "structure. Respect the swing 'source': 'imported' is a user-curated anchor and "
            "should be preferred over the 'computed' one when both exist. "
            "If the technical block contains 'patterns' (e.g. Head & Shoulders, Double "
            "Top/Bottom, triangles), treat each as ONE probabilistic input weighted by its "
            "'confidence' and 'status' (a 'confirmed' break matters more than a 'forming' "
            "one) and by its 'validation' verdict from the volume Risk agent "
            "('confirmed'/'weak'/'pending'/'veto'/'stale') — a veto or stale pattern carries "
            "little weight. Classic chart patterns are subjective with mixed reliability, so let "
            "them nuance timing/conviction and never override the fundamental thesis. "
            "When a 'confluence' block is present, treat it as the FUSED verdict of the technical "
            "agents (trend, structure, momentum, the volume-validated pattern, and volume/OBV): "
            "its 'bias' (Bullish…Bearish), 'score', 'strength', and especially its explicit "
            "'agreements' and 'conflicts' are your primary technical read. Lead the technical "
            "reasoning from it — a strong, high-agreement bias raises timing conviction, while "
            "listed conflicts or a 'Mixed'/weak verdict should temper it — and cite it in a "
            "factor when it is decisive. It still modulates, never overrides, the fundamental thesis. "
            "Technical signals modulate timing and confidence; fundamentals and notes drive "
            "the core thesis. "
            "Respond only with JSON using keys: action, confidence, rationale, factors, noteSynthesis. "
            "action: buy | sell | hold | watch. "
            "confidence: high | medium | low. "
            "factors: array of short strings, each citing the SPECIFIC input that drove it "
            "(e.g. 'Forward P/E 18 vs 22% revenue growth — reasonable', 'Debt/equity 180 with "
            "negative FCF — balance-sheet risk', 'Trades 12% below 1Y analyst mean'). "
            "rationale: 2-4 sentences integrating fundamentals, notes, and market context. "
            "noteSynthesis: pass through the provided combined noteSynthesis; you may add a brief "
            "integratedSummary field if helpful. "
            "Focus on evidence-based synthesis. Do not invent position-sizing rules."
        )

    def _assessment_user_prompt(
        self, context: dict[str, Any], hard_trigger: dict[str, Any] | None = None
    ) -> str:
        # When a hard threshold event has fired, the action is already decided; the
        # LLM is constrained to explain conviction rather than re-pick the action.
        constraint = ""
        if hard_trigger:
            action = hard_trigger["action"]
            reason = hard_trigger.get("reason", "a price threshold was crossed")
            constraint = (
                "\n\nHARD CONSTRAINT — DO NOT VIOLATE: A deterministic threshold event has "
                f'already decided the action as "{action}" because {reason}. Return '
                f'"action": "{action}" EXACTLY and do not change it. Use "rationale" and '
                '"factors" to explain the conviction behind this action given the '
                "fundamentals, technicals, and news — explicitly note whether the broader "
                "picture supports or cautions against it."
            )
        return (
            "Produce a combined assessment for this symbol.\n\n"
            f"Context JSON:\n{json.dumps(context, indent=2)}"
            f"{constraint}"
        )

    def _normalize_synthesis(self, result: dict[str, Any], provider: str) -> dict[str, Any]:
        sentiment = str(result.get("sentiment", "neutral")).strip().lower()
        if sentiment not in self.VALID_SENTIMENT:
            sentiment = "neutral"

        growth = result.get("growthTrajectory", [])
        if not isinstance(growth, list):
            growth = []
        projections = result.get("revenueProjections", [])
        if not isinstance(projections, list):
            projections = []
        catalysts = result.get("catalystsToWatch", [])
        if not isinstance(catalysts, list):
            catalysts = []

        summary = str(result.get("summary", "")).strip()
        if not summary:
            summary = "Note reviewed; see structured fields for details."

        normalized = {
            "summary": summary,
            "growthTrajectory": [self._normalize_dict(item) for item in growth[:8]],
            "revenueProjections": [self._normalize_dict(item) for item in projections[:5]],
            "catalystsToWatch": [self._normalize_dict(item) for item in catalysts[:5]],
            "sentiment": sentiment,
            "provider": provider,
        }
        if result.get("integratedSummary"):
            normalized["integratedSummary"] = str(result["integratedSummary"]).strip()
        return normalized

    def _normalize_assessment(
        self,
        result: dict[str, Any],
        provider: str,
        combined: dict[str, Any],
    ) -> dict[str, Any]:
        action = str(result.get("action", "hold")).strip().lower()
        confidence = str(result.get("confidence", "medium")).strip().lower()
        if action not in self.VALID_ACTIONS:
            action = "hold"
        if confidence not in self.VALID_CONFIDENCE:
            confidence = "medium"

        factors = result.get("factors", [])
        if isinstance(factors, str):
            factors = [factors]
        if not isinstance(factors, list):
            factors = []

        rationale = str(result.get("rationale", "")).strip()
        if not rationale:
            rationale = "No rationale provided."

        note_synthesis = result.get("noteSynthesis")
        if isinstance(note_synthesis, dict) and note_synthesis.get("summary"):
            note_synthesis = self._normalize_synthesis(note_synthesis, provider)
        else:
            note_synthesis = combined

        return {
            "action": action,
            "confidence": confidence,
            "rationale": rationale,
            "factors": [str(item) for item in factors],
            "noteSynthesis": note_synthesis,
            "provider": provider,
        }

    @staticmethod
    def _empty_synthesis() -> dict[str, Any]:
        return {
            "summary": "No note synthesis available.",
            "growthTrajectory": [],
            "revenueProjections": [],
            "catalystsToWatch": [],
            "sentiment": "neutral",
            "provider": "rules",
        }

    @staticmethod
    def _normalize_dict(item: Any) -> dict[str, Any]:
        if isinstance(item, dict):
            return {str(key): value for key, value in item.items()}
        return {"value": str(item)}

    @staticmethod
    def _extract_period(text: str, position: int) -> str:
        window = text[max(0, position - 80): position + 80]
        match = re.search(r"Q[1-4]\s*20\d{2}|Q[1-4]", window, re.IGNORECASE)
        return match.group(0) if match else ""

    @staticmethod
    def _next_quarter(last_quarter: str | None) -> str:
        if not last_quarter:
            return "Next quarter"
        match = re.match(r"Q([1-4])\s*(20(\d{2}))?", last_quarter, re.IGNORECASE)
        if not match:
            return "Next quarter"
        q = int(match.group(1))
        year = int(match.group(2)) if match.group(2) else 2026
        if q == 4:
            return f"Q1 {year + 1}"
        return f"Q{q + 1} {year}"

    def _post_json(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
        max_retries: int = 4,
    ) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request_headers = {"Content-Type": "application/json"}
        if headers:
            request_headers.update(headers)

        ssl_context = ssl.create_default_context(cafile=certifi.where())
        last_error = ""

        for attempt in range(max_retries):
            req = urllib.request.Request(url, data=body, headers=request_headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=90, context=ssl_context) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                last_error = detail
                if exc.code == 429 and attempt < max_retries - 1:
                    wait = self._parse_retry_seconds(detail) or (5 * (attempt + 1))
                    logging.info("Gemini rate limit — waiting %ss before retry %s/%s", wait, attempt + 2, max_retries)
                    time.sleep(wait)
                    continue
                raise RuntimeError(f"LLM request failed ({exc.code}): {detail}") from exc
            except urllib.error.URLError as exc:
                raise RuntimeError(f"LLM network error: {exc.reason}") from exc

        raise RuntimeError(f"LLM request failed after retries: {last_error}")

    @staticmethod
    def _parse_retry_seconds(detail: str) -> int | None:
        match = re.search(r"retry in (\d+(?:\.\d+)?)s", detail, re.IGNORECASE)
        if match:
            return max(2, int(float(match.group(1))) + 1)
        return None

    @staticmethod
    def extract_json(text: str) -> dict[str, Any]:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError("No JSON object found in LLM response.")
        return json.loads(match.group(0))
