import contextvars
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from db.database import get_connection, get_current_user_id
from services.alerts_service import AlertsService
from services.assessment_overlay_service import AssessmentOverlayService
from services.fib_service import FibService
from services.fundamentals_service import FundamentalsService
from services.holdings_service import HoldingsService
from services.llm_client import LLMClient
from services.portfolio_service import PortfolioService
from services.preferences_service import PreferencesService
from services.proposal_service import ProposalService
from services.screening_service import ScreeningService
from services.symbol_assessment_service import DEDUP_BASE_ASSESSMENT, SymbolAssessmentService
from services.technical_service import TechnicalService
from services.technical_signals_service import TechnicalSignalsService
from services.track_record_service import TrackRecordService

# Tier 1+2: feed computed technical signals (multi-timeframe trend/momentum +
# adaptive Fibonacci swing) into the assessment. Toggle off to A/B against the
# prior behaviour.
ASSESSMENT_TECHNICALS = os.environ.get("ASSESSMENT_TECHNICALS", "1").lower() not in (
    "0",
    "false",
    "no",
    "off",
)

# Tier 4: capture each assessment's recommendation (and any detected chart
# patterns) as a forward-looking "signal outcome" so the system can later score
# its own track record. Read-only reporting; no auto-calibration yet.
TRACK_RECORD = os.environ.get("TRACK_RECORD", "1").lower() not in (
    "0",
    "false",
    "no",
    "off",
)
TRACK_RECORD_HORIZON_DAYS = max(1, int(os.environ.get("TRACK_RECORD_HORIZON_DAYS", "21")))

_ACTION_DIRECTION = {
    "buy": "bullish",
    "sell": "bearish",
    "hold": "neutral",
    "watch": "neutral",
}


def _pattern_direction(pattern_type: str | None) -> str:
    t = (pattern_type or "").strip().lower()
    if t == "bullish":
        return "bullish"
    if t == "bearish":
        return "bearish"
    return "neutral"


def _confluence_direction(bias: str | None) -> str:
    b = (bias or "").strip().lower()
    if "bull" in b:
        return "bullish"
    if "bear" in b:
        return "bearish"
    return "neutral"


class AssessmentService:
    MAX_ASSESSMENTS_PER_SYMBOL = 3

    def __init__(self):
        self.portfolio_service = PortfolioService()
        self.holdings_service = HoldingsService()
        self.alerts_service = AlertsService()
        self.fib_service = FibService()
        self.screening_service = ScreeningService()
        self.fundamentals_service = FundamentalsService()
        self.technical_service = TechnicalService()
        self.technical_signals_service = TechnicalSignalsService()
        self.llm_client = LLMClient()
        self.assess_workers = max(1, int(os.environ.get("ASSESS_WORKERS", "6")))
        self.symbol_assessment_service = SymbolAssessmentService()
        self.overlay_service = AssessmentOverlayService(self.llm_client)
        self.proposal_service = ProposalService()
        self.preferences_service = PreferencesService()
        self.track_record_service = TrackRecordService()

    def _proposal_extras(self) -> dict[str, Any]:
        """Shared inputs for proposal scoring (prefs, income, track-record scales)."""
        fit_prefs = self.preferences_service.get_portfolio_fit()
        portfolio_annual_dividend = 0.0
        for holding in self.holdings_service.list_holdings():
            per_sh = holding.get("annualDividend")
            qty = holding.get("quantity") or 0
            if isinstance(per_sh, (int, float)) and qty:
                portfolio_annual_dividend += float(per_sh) * float(qty)
        track_summary = None
        if TRACK_RECORD:
            try:
                track_summary = self.track_record_service.get_summary()
            except Exception:  # noqa: BLE001 - scoring must not fail assess
                track_summary = None
        return {
            "fit_prefs": fit_prefs,
            "portfolio_annual_dividend": round(portfolio_annual_dividend, 2),
            "track_record_summary": track_summary,
        }

    def _compute_assessment(
        self, symbol: str, extras: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Build context and run assessment (shared base + personal overlay when enabled)."""
        symbol = symbol.upper()
        symbol_data = self.portfolio_service.get_symbol(symbol)
        if symbol_data is None:
            raise ValueError(f"Symbol {symbol} not found.")
        extras = extras or self._proposal_extras()
        context = self._build_context(symbol_data)
        context["fitPrefs"] = extras.get("fit_prefs")
        context["portfolioAnnualDividend"] = extras.get("portfolio_annual_dividend")
        if DEDUP_BASE_ASSESSMENT:
            base = self.symbol_assessment_service.get_or_compute_today(symbol)
            result = self.overlay_service.apply(base, context)
            if base.get("llmFallback"):
                result["llmFallback"] = True
                result["llmError"] = base.get("llmError")
        else:
            result = self.llm_client.generate_assessment(context)
        return result, context

    def assess_symbol(self, symbol: str) -> dict[str, Any]:
        from services.plan_service import ensure_can_manual_ai_action, record_manual_ai_action

        ensure_can_manual_ai_action()
        result, context = self._compute_assessment(symbol)
        saved = self._save_assessment(symbol.upper(), result, context)
        record_manual_ai_action()
        return saved

    def assess_portfolio(self, symbols: list[str] | None = None) -> list[dict[str, Any]]:
        from services.plan_service import ensure_can_manual_ai_action, record_manual_ai_action

        ensure_can_manual_ai_action()

        if symbols:
            symbol_list = [str(symbol).upper() for symbol in symbols]
        else:
            symbol_list = [item["symbol"] for item in self.portfolio_service.list_symbols()]
        if not symbol_list:
            return []

        # The per-symbol LLM call dominates wall time (~15s each on Gemini), so a
        # sequential pass over a full portfolio can take many minutes and makes the
        # UI look stuck. Run the network-bound compute concurrently, then persist
        # serially on this thread (SQLite writes stay single-threaded and ordered).
        computed: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        first_error: Exception | None = None
        workers = min(self.assess_workers, len(symbol_list))
        # Worker threads must see the same current user as this request. A single
        # Context can only be entered by one thread at a time, so each task gets
        # its own copy of the current context (captured here on the request
        # thread) — sharing one ctx.run across the pool raises "cannot enter
        # context: ... is already entered".
        extras = self._proposal_extras()
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {
                executor.submit(
                    contextvars.copy_context().run, self._compute_assessment, sym, extras
                ): sym
                for sym in symbol_list
            }
            for future, sym in future_map.items():
                try:
                    computed[sym] = future.result()
                except Exception as exc:  # noqa: BLE001 - surfaced/handled below
                    if first_error is None:
                        first_error = exc
                    logging.warning("Assessment compute failed for %s: %s", sym, exc)

        # Preserve the original "unknown symbol -> 404" contract for explicit requests.
        if symbols and isinstance(first_error, ValueError):
            raise first_error

        assessments = []
        for sym in symbol_list:
            if sym not in computed:
                continue
            result, context = computed[sym]
            assessments.append(self._save_assessment(sym, result, context))
        if assessments:
            record_manual_ai_action()
        return assessments

    def list_assessments(self, symbol: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        query = """
            SELECT id, symbol, action, confidence, rationale, factors,
                   note_synthesis, trading_recommendation, provider, created_at
            FROM assessments
            WHERE user_id = %s
        """
        params: list[Any] = [get_current_user_id()]
        if symbol:
            query += " AND symbol = %s"
            params.append(symbol.upper())
        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)

        with get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_assessment(row) for row in rows]

    def latest_overview(self) -> list[dict[str, Any]]:
        """Latest assessment per symbol, joined with live price/target context.

        Powers the portfolio-wide "Latest Assessments" overview (Summary panel).
        Newest first."""
        user_id = get_current_user_id()
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT a.symbol, a.action, a.confidence, a.rationale, a.factors,
                       a.provider, a.created_at, a.trading_recommendation,
                       m.current_price, s.target_price, m.analyst_target_1y
                FROM (
                    SELECT *, ROW_NUMBER() OVER (
                        PARTITION BY symbol ORDER BY created_at DESC, id DESC
                    ) AS rn
                    FROM assessments
                    WHERE user_id = %s
                ) a
                JOIN symbols s ON s.user_id = %s AND s.symbol = a.symbol
                LEFT JOIN symbol_market m ON m.symbol = a.symbol
                WHERE a.rn = 1
                ORDER BY a.created_at DESC, a.symbol
                """,
                (user_id, user_id),
            ).fetchall()

        out: list[dict[str, Any]] = []
        for row in rows:
            price = row["current_price"]
            target = row["target_price"]
            analyst = row["analyst_target_1y"]
            upside = (
                round((target - price) / price * 100, 2)
                if price and target and price > 0
                else None
            )
            analyst_upside = (
                round((analyst - price) / price * 100, 2)
                if price and analyst and price > 0
                else None
            )
            proposal = self._parse_json_field(row["trading_recommendation"], default=None)
            slim_proposal = None
            if isinstance(proposal, dict) and proposal.get("schemaVersion") is not None:
                scores = proposal.get("scores") or {}
                slim_proposal = {
                    "scores": {
                        "total": scores.get("total"),
                        "state": scores.get("state"),
                        "trigger": scores.get("trigger"),
                        "portfolioFit": scores.get("portfolioFit"),
                    },
                    "confidence": proposal.get("confidence"),
                    "bandBias": proposal.get("bandBias"),
                    "attention": proposal.get("attention"),
                    "intent": proposal.get("intent"),
                }
            item: dict[str, Any] = {
                    "symbol": row["symbol"],
                    "action": row["action"],
                    "confidence": row["confidence"],
                    "rationale": row["rationale"],
                    "factors": self._parse_json_field(row["factors"], default=[]),
                    "provider": row["provider"],
                    "assessedAt": row["created_at"],
                    "currentPrice": price,
                    "targetPrice": target,
                    "analystTarget1y": analyst,
                    "upsidePct": upside,
                    "analystUpsidePct": analyst_upside,
            }
            if slim_proposal is not None:
                item["proposal"] = slim_proposal
            out.append(item)
        return out

    def band_divergence(self) -> list[dict[str, Any]]:
        """Compare latest *new* SAI (band-based) vs legacy technical/news SAI.

        Returns only symbols where both are present and disagree in directional
        sentiment (buy / hold / sell)."""

        def _action_sentiment(action: str) -> str:
            a = action.lower()
            if "buy" in a or "add" in a:
                return "buy"
            if "sell" in a or "avoid" in a or "trim" in a:
                return "sell"
            return "hold"

        user_id = get_current_user_id()
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT symbol, action, trading_recommendation, created_at
                FROM (
                    SELECT *, ROW_NUMBER() OVER (
                        PARTITION BY symbol ORDER BY created_at DESC, id DESC
                    ) AS rn
                    FROM assessments
                    WHERE user_id = %s
                ) ranked
                WHERE rn = 1
                  AND trading_recommendation IS NOT NULL
                ORDER BY symbol
                """,
                (user_id,),
            ).fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            proposal = self._parse_json_field(row["trading_recommendation"], default=None)
            if not proposal or not isinstance(proposal, dict):
                continue
            legacy = proposal.get("legacySai") or {}
            legacy_action = str(legacy.get("action") or "").strip().lower()
            if not legacy_action:
                continue
            scores = proposal.get("scores") or {}
            total = scores.get("total")
            if total is None:
                continue
            new_sai_action = str(row["action"] or "").strip().lower()
            new_sai_sentiment = _action_sentiment(new_sai_action)
            legacy_sentiment = _action_sentiment(legacy_action)
            if new_sai_sentiment == legacy_sentiment:
                continue
            band = proposal.get("bandBias") or {}
            results.append(
                {
                    "symbol": row["symbol"],
                    "saiAction": new_sai_action,
                    "saiSentiment": new_sai_sentiment,
                    "legacySaiAction": legacy_action,
                    "legacySaiSentiment": legacy_sentiment,
                    "proposalTotal": int(total),
                    "bandCode": band.get("code"),
                    "bandLabel": band.get("label"),
                    "legacySource": legacy.get("actionSource"),
                    "legacyNote": legacy.get("note"),
                    "assessedAt": row["created_at"],
                    "note": (
                        f"New SAI says '{new_sai_action}' but legacy technical/news "
                        f"said '{legacy_action}'"
                    ),
                }
            )
        return results

    def delete_assessment(self, assessment_id: int, symbol: str | None = None) -> bool:
        query = "DELETE FROM assessments WHERE id = %s AND user_id = %s"
        params: list[Any] = [assessment_id, get_current_user_id()]
        if symbol:
            query += " AND symbol = %s"
            params.append(symbol.upper())

        with get_connection() as conn:
            cursor = conn.execute(query, params)
            conn.commit()
            return cursor.rowcount > 0

    def _build_context(self, symbol_data: dict[str, Any]) -> dict[str, Any]:
        symbol = symbol_data["symbol"]
        fib = self.fib_service.get_levels(symbol)
        holding = self._holding_with_weight(symbol)
        screening = self.screening_service._score_symbol(symbol_data)
        notes = symbol_data.get("notes", [])

        note_syntheses = [note["synthesis"] for note in notes if note.get("synthesis")]
        unsynthesized = sum(1 for note in notes if not note.get("synthesis"))
        enrichment = self.fundamentals_service.get_enrichment(symbol)

        trade_below = symbol_data.get("tradeBelowPrice")
        trade_above = symbol_data.get("tradeAbovePrice")
        buy_below = trade_below if trade_below is not None else symbol_data.get("buyBelow")
        sell_above = trade_above if trade_above is not None else symbol_data.get("sellAbove")

        return {
            "symbol": symbol,
            "companyName": symbol_data.get("companyName"),
            "currentPrice": symbol_data.get("currentPrice"),
            "targetPrice": symbol_data.get("targetPrice"),
            "analystTarget1y": symbol_data.get("analystTarget1y"),
            "buyBelow": buy_below,
            "sellAbove": sell_above,
            "noteSyntheses": note_syntheses,
            "unsynthesizedNoteCount": unsynthesized,
            "alerts": self.alerts_service.list_alerts(symbol=symbol, status="active"),
            "fibLevels": fib.get("levels", []) if fib else [],
            "screening": {
                "score": screening.get("score"),
                "upsidePct": screening.get("upsidePct"),
                "flags": screening.get("flags", []),
                "fibDistancePct": screening.get("fibDistancePct"),
                "tradeBelowPrice": symbol_data.get("tradeBelowPrice"),
                "tradeBelowShares": symbol_data.get("tradeBelowShares"),
                "tradeAbovePrice": symbol_data.get("tradeAbovePrice"),
                "tradeAboveShares": symbol_data.get("tradeAboveShares"),
                "personalTarget": symbol_data.get("targetPrice"),
                "analystTarget1y": symbol_data.get("analystTarget1y"),
            },
            "fundamentals": enrichment.get("fundamentals", {}),
            "recentNews": enrichment.get("recentNews", []),
            "holding": holding,
            "intentOverride": symbol_data.get("intentOverride"),
            "tradeBelowPrice": symbol_data.get("tradeBelowPrice"),
            "tradeBelowShares": symbol_data.get("tradeBelowShares"),
            "tradeAbovePrice": symbol_data.get("tradeAbovePrice"),
            "tradeAboveShares": symbol_data.get("tradeAboveShares"),
            "technical": self._build_technical(symbol) if ASSESSMENT_TECHNICALS else None,
        }

    def _build_technical(self, symbol: str) -> dict[str, Any] | None:
        """Computed multi-timeframe signals, with an imported snapshot's
        hand-anchored swing/Fibonacci taking precedence when present — unless
        the user has opted to prefer computed trends over imported TA."""
        from db.database import get_prefer_computed_trends

        signals = self.technical_signals_service.get_signals(symbol)
        block: dict[str, Any] = dict(signals) if signals else {}

        if get_prefer_computed_trends():
            return block or None

        snapshot = self.technical_service.get_snapshot(symbol)
        if snapshot and snapshot.get("trends"):
            block["trendWaves"] = self.technical_service.trend_waves_for_symbol(symbol, snapshot)
        imported_fib = (
            self.technical_service.fib_from_snapshot(symbol, snapshot) if snapshot else None
        )
        if imported_fib and imported_fib.get("levels"):
            block["swing"] = {
                "source": "imported",
                "swingHigh": imported_fib.get("swingHigh"),
                "swingLow": imported_fib.get("swingLow"),
                "period": imported_fib.get("period"),
                "anchorTrend": imported_fib.get("anchorTrend"),
                "levels": imported_fib.get("levels", []),
            }

        return block or None

    def _holding_with_weight(self, symbol: str) -> dict[str, Any] | None:
        holdings = self.holdings_service.list_holdings()
        total_market_value = sum(
            holding["marketValue"] for holding in holdings if holding.get("marketValue")
        )
        holding = self.holdings_service.get_holding(symbol)
        if holding is None:
            return None
        if holding.get("marketValue") and total_market_value:
            holding = {**holding, "weightPct": round(holding["marketValue"] / total_market_value * 100, 2)}
        return holding

    def _recent_actions(self, conn, user_id: int, symbol: str, limit: int = 5) -> list[str]:
        rows = conn.execute(
            """
            SELECT action FROM assessments
            WHERE user_id = %s AND symbol = %s
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            (user_id, symbol, limit),
        ).fetchall()
        return [row["action"] for row in rows]

    def _save_assessment(
        self,
        symbol: str,
        result: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        factors_json = json.dumps(result.get("factors", []))
        synthesis_json = json.dumps(result.get("noteSynthesis", {}))
        user_id = get_current_user_id()
        with get_connection() as conn:
            previous = conn.execute(
                """
                SELECT action, confidence FROM assessments
                WHERE user_id = %s AND symbol = %s
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (user_id, symbol),
            ).fetchone()
            previous_actions = self._recent_actions(conn, user_id, symbol)
            extras = self._proposal_extras()
            proposal = self.proposal_service.build(
                symbol=symbol,
                action=result["action"],
                confidence=result["confidence"],
                rationale=result.get("rationale") or "",
                factors=result.get("factors") or [],
                action_source=result.get("actionSource"),
                context=context,
                previous_actions=previous_actions,
                fit_prefs=extras["fit_prefs"],
                track_record_summary=extras["track_record_summary"],
                portfolio_annual_dividend=extras["portfolio_annual_dividend"],
            )
            # Persist overlay/Pass-1 action — not proposal band Action (that remains
            # on proposal for Score / Attention). Pass 2 may only have nudged Hold→Watch.
            stored_action = str(result.get("action") or "hold").lower()
            stored_confidence = str(result.get("confidence") or "medium").lower()
            proposal_json = json.dumps(proposal)
            cursor = conn.execute(
                """
                INSERT INTO assessments (
                    user_id, symbol, action, confidence, rationale, factors,
                    note_synthesis, trading_recommendation, provider
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    user_id,
                    symbol,
                    stored_action,
                    stored_confidence,
                    result["rationale"],
                    factors_json,
                    synthesis_json,
                    proposal_json,
                    result["provider"],
                ),
            )
            new_id = cursor.fetchone()["id"]
            stored_result = {**result, "action": stored_action, "confidence": stored_confidence}
            self._record_recommendation_change(conn, user_id, symbol, previous, stored_result)
            if TRACK_RECORD:
                self._capture_signal_outcomes(
                    conn, user_id, symbol, new_id, stored_result, context, proposal=proposal
                )
            self._trim_assessment_history(conn, user_id, symbol)
            conn.commit()
            row = conn.execute(
                """
                SELECT id, symbol, action, confidence, rationale, factors,
                       note_synthesis, trading_recommendation, provider, created_at
                FROM assessments WHERE id = %s
                """,
                (new_id,),
            ).fetchone()

        assessment = self._row_to_assessment(row)
        if result.get("llmFallback"):
            assessment["llmFallback"] = True
            assessment["llmError"] = result.get("llmError")
        # Surface what drove the action (rule_hard_trigger | llm | rules_fallback).
        # Additive only — there is no DB column, so it rides on the returned payload.
        if result.get("actionSource"):
            assessment["actionSource"] = result["actionSource"]
        if result.get("baseAssessmentDate"):
            assessment["baseAssessmentDate"] = result["baseAssessmentDate"]
        if result.get("baseFromCache") is not None:
            assessment["baseFromCache"] = result["baseFromCache"]
        assessment["context"] = context
        # Prefer freshly built proposal (row parse is identical, but keeps types tight).
        assessment["proposal"] = proposal
        return assessment

    def _record_recommendation_change(
        self, conn, user_id: int, symbol: str, previous, result: dict[str, Any]
    ) -> None:
        """Log a changelog row when the discrete action changes vs the prior assessment.

        Skips the very first assessment for a symbol (no prior action to compare).
        """
        if previous is None:
            return
        old_action = previous["action"]
        new_action = result["action"]
        if old_action == new_action:
            return
        conn.execute(
            """
            INSERT INTO recommendation_changelog (
                user_id, symbol, old_action, new_action, old_confidence, new_confidence, provider
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                user_id,
                symbol,
                old_action,
                new_action,
                previous["confidence"],
                result["confidence"],
                result.get("provider"),
            ),
        )

    def _capture_signal_outcomes(
        self,
        conn,
        user_id: int,
        symbol: str,
        assessment_id: int,
        result: dict[str, Any],
        context: dict[str, Any],
        proposal: dict[str, Any] | None = None,
    ) -> None:
        """Snapshot the recommendation + detected patterns as forward-looking bets.

        Entry price is the price at assessment time; the evaluator later compares it
        to the price once the horizon elapses. To avoid flooding on repeated
        re-assessments, we keep at most one *pending* capture per (symbol, kind,
        label). Recommendation rows also store confidence / Fit / band strength.
        """
        from services.track_record_service import confluence_outcome_meta, strength_from_proposal

        entry_price = context.get("currentPrice")
        if not entry_price or entry_price <= 0:
            return

        captures: list[tuple[str, str, str]] = []  # (kind, label, direction)
        action = str(result.get("action", "hold")).strip().lower()
        captures.append(
            ("recommendation", action, _ACTION_DIRECTION.get(action, "neutral"))
        )

        technical = context.get("technical") or {}
        for pattern in technical.get("patterns") or []:
            name = pattern.get("name")
            if not name:
                continue
            # Don't record patterns the Risk agent vetoed (weak volume) or marked
            # stale/played-out as forward-looking bets — they'd pollute the record.
            if (pattern.get("validation") or {}).get("verdict") in ("veto", "stale"):
                continue
            captures.append(("pattern", name, _pattern_direction(pattern.get("type"))))

        # Capture the Confluence agent's fused bias as its own forward-looking bet
        # so its track record can be scored alongside patterns/recommendations. Only
        # directional verdicts are falsifiable, so skip 'Mixed'. Label by direction
        # so a later bias flip records a distinct, scorable signal. Lean vs Strong,
        # score, and conflicts are stored as metadata (label stays Bullish/Bearish).
        confluence = technical.get("confluence") or {}
        conf_dir = _confluence_direction(confluence.get("bias"))
        confluence_meta = confluence_outcome_meta(confluence) if conf_dir in ("bullish", "bearish") else None
        if conf_dir in ("bullish", "bearish"):
            captures.append(("confluence", conf_dir.title(), conf_dir))

        # SAI episode boundary: closing a prior pending recommendation at this
        # capture's price so Buy@T1 → Sell@T2 is scored on T1→T2, not a full
        # overlapping horizon. Same-action pending rows are left open (dedup).
        rec_labels = [label for kind, label, _direction in captures if kind == "recommendation"]
        if rec_labels:
            self.track_record_service.early_close_conflicting_recommendations(
                conn,
                user_id,
                symbol,
                new_label=rec_labels[0],
                eval_price=float(entry_price),
            )

        confidence, fit_total, band_code = strength_from_proposal(
            proposal, result.get("confidence")
        )

        for kind, label, direction in captures:
            pending = conn.execute(
                """
                SELECT 1 FROM signal_outcomes
                WHERE user_id = %s AND symbol = %s AND kind = %s AND label = %s
                  AND outcome IS NULL
                LIMIT 1
                """,
                (user_id, symbol, kind, label),
            ).fetchone()
            if pending is not None:
                continue
            if kind == "recommendation":
                conn.execute(
                    """
                    INSERT INTO signal_outcomes (
                        user_id, symbol, assessment_id, kind, label, direction,
                        entry_price, horizon_days, eval_due_at,
                        confidence, fit_total, band_code
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        to_char(
                            timezone('UTC', now()) + (%s || ' days')::interval,
                            'YYYY-MM-DD HH24:MI:SS'
                        ),
                        %s, %s, %s
                    )
                    """,
                    (
                        user_id,
                        symbol,
                        assessment_id,
                        kind,
                        label,
                        direction,
                        float(entry_price),
                        TRACK_RECORD_HORIZON_DAYS,
                        TRACK_RECORD_HORIZON_DAYS,
                        confidence,
                        fit_total,
                        band_code,
                    ),
                )
            elif kind == "confluence" and confluence_meta is not None:
                conn.execute(
                    """
                    INSERT INTO signal_outcomes (
                        user_id, symbol, assessment_id, kind, label, direction,
                        entry_price, horizon_days, eval_due_at,
                        confluence_band, confluence_score, agree_count,
                        conflict_count, signal_strength
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        to_char(
                            timezone('UTC', now()) + (%s || ' days')::interval,
                            'YYYY-MM-DD HH24:MI:SS'
                        ),
                        %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        user_id,
                        symbol,
                        assessment_id,
                        kind,
                        label,
                        direction,
                        float(entry_price),
                        TRACK_RECORD_HORIZON_DAYS,
                        TRACK_RECORD_HORIZON_DAYS,
                        confluence_meta.get("confluenceBand"),
                        confluence_meta.get("confluenceScore"),
                        confluence_meta.get("agreeCount"),
                        confluence_meta.get("conflictCount"),
                        confluence_meta.get("signalStrength"),
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO signal_outcomes (
                        user_id, symbol, assessment_id, kind, label, direction,
                        entry_price, horizon_days, eval_due_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        to_char(
                            timezone('UTC', now()) + (%s || ' days')::interval,
                            'YYYY-MM-DD HH24:MI:SS'
                        )
                    )
                    """,
                    (
                        user_id,
                        symbol,
                        assessment_id,
                        kind,
                        label,
                        direction,
                        float(entry_price),
                        TRACK_RECORD_HORIZON_DAYS,
                        TRACK_RECORD_HORIZON_DAYS,
                    ),
                )

    def count_recommendation_changes(self) -> int:
        """Total number of logged recommendation changes (for the Summary header)."""
        user_id = get_current_user_id()
        with get_connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM recommendation_changelog WHERE user_id = %s",
                (user_id,),
            ).fetchone()
        return int(row["n"]) if row else 0

    def list_recommendation_changes(self, limit: int | None = 8) -> list[dict[str, Any]]:
        user_id = get_current_user_id()
        with get_connection() as conn:
            query = """
                SELECT id, symbol, old_action, new_action, old_confidence,
                       new_confidence, provider, created_at
                FROM recommendation_changelog
                WHERE user_id = %s
                ORDER BY created_at DESC, id DESC
            """
            params: list[Any] = [user_id]
            if limit is not None and limit > 0:
                query += " LIMIT %s"
                params.append(limit)
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "id": row["id"],
                "symbol": row["symbol"],
                "oldAction": row["old_action"],
                "newAction": row["new_action"],
                "oldConfidence": row["old_confidence"],
                "newConfidence": row["new_confidence"],
                "provider": row["provider"],
                "createdAt": row["created_at"],
            }
            for row in rows
        ]

    def _trim_assessment_history(self, conn, user_id: int, symbol: str) -> None:
        rows = conn.execute(
            """
            SELECT id FROM assessments
            WHERE user_id = %s AND symbol = %s
            ORDER BY created_at DESC, id DESC
            """,
            (user_id, symbol),
        ).fetchall()
        stale_ids = [row["id"] for row in rows[self.MAX_ASSESSMENTS_PER_SYMBOL :]]
        if not stale_ids:
            return
        placeholders = ",".join(["%s"] * len(stale_ids))
        conn.execute(
            f"DELETE FROM assessments WHERE user_id = %s AND id IN ({placeholders})",
            [user_id, *stale_ids],
        )

    def _row_to_assessment(self, row) -> dict[str, Any]:
        factors = self._parse_json_field(row["factors"], default=[])
        note_synthesis = self._parse_json_field(row["note_synthesis"], default={})
        proposal = self._parse_json_field(row["trading_recommendation"], default=None)
        # Legacy rows may store non-proposal text in trading_recommendation — ignore.
        if not isinstance(proposal, dict) or proposal.get("schemaVersion") is None:
            proposal = None

        out = {
            "id": row["id"],
            "symbol": row["symbol"],
            "action": row["action"],
            "confidence": row["confidence"],
            "rationale": row["rationale"],
            "factors": factors,
            "noteSynthesis": note_synthesis,
            "provider": row["provider"],
            "createdAt": row["created_at"],
        }
        if proposal is not None:
            out["proposal"] = proposal
        return out

    def get_proposal(self, symbol: str) -> dict[str, Any] | None:
        """Latest proposal for a symbol — stored if present, else rebuilt from latest assess."""
        symbol = symbol.upper()
        if self.portfolio_service.get_symbol(symbol) is None:
            return None
        extras = self._proposal_extras()
        history = self.list_assessments(symbol=symbol, limit=5)
        if not history:
            symbol_data = self.portfolio_service.get_symbol(symbol)
            context = self._build_context(symbol_data)
            return self.proposal_service.build(
                symbol=symbol,
                action="hold",
                confidence="medium",
                rationale="Run Assess Symbol to generate a full proposal.",
                factors=[],
                action_source=None,
                context=context,
                previous_actions=[],
                fit_prefs=extras["fit_prefs"],
                track_record_summary=extras["track_record_summary"],
                portfolio_annual_dividend=extras["portfolio_annual_dividend"],
            )
        latest = history[0]
        # Rebuild when prefs may have changed; always refresh fitExtensions from prefs.
        previous_actions = [a["action"] for a in history[1:]]
        symbol_data = self.portfolio_service.get_symbol(symbol)
        context = self._build_context(symbol_data) if symbol_data else None
        return self.proposal_service.build_from_assessment(
            latest,
            context=context,
            previous_actions=previous_actions,
            fit_prefs=extras["fit_prefs"],
            track_record_summary=extras["track_record_summary"],
            portfolio_annual_dividend=extras["portfolio_annual_dividend"],
        )

    @staticmethod
    def _parse_json_field(raw, default):
        if not raw:
            return default
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            if isinstance(default, list):
                return [raw]
            return default
