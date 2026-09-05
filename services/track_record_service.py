"""Tier 4: Agent Signal Record — self-scoring for agent signals (recommendations,
patterns, confluence) captured when an assessment run completes.

Each assessment captures a forward-looking "signal outcome" (see
AssessmentService._capture_signal_outcomes). Once the configured horizon elapses,
the evaluator compares the entry price to the current price and labels the bet a
win/loss/neutral based on the signal's direction.

Recommendation (SAI) bets use **episode scoring**: an open action is early-closed
when a later assessment publishes a different action, so Buy@T1 → Sell@T2 is
judged on the T1→T2 move (using the flip capture's entry price), not on a full
horizon that overlaps the next action.

This is intentionally read-only with respect to future assessments: we measure
the track record but do not yet auto-calibrate (re-weight) future signals.
"""

import logging
import json
import os
from typing import Any

from db.database import get_connection, get_current_user_id
from services.portfolio_service import PortfolioService

# A dead-band so tiny moves do not count as a "win" or "loss". A bullish call
# wins only if the forward return clears +BAND; a bearish call wins only if it
# falls past -BAND; anything inside the band is "neutral".
TRACK_RECORD_BAND_PCT = float(os.environ.get("TRACK_RECORD_BAND_PCT", "2.0"))
TRACK_RECORD_HORIZON_DAYS = max(1, int(os.environ.get("TRACK_RECORD_HORIZON_DAYS", "21")))

# Filter-in-query era floor for Summary / learning aggregates. Rows with
# captured_at before this date are excluded (not deleted). Default = P0 ship
# day for episode scoring + Conf·Score strength (2026-08-02). Empty string
# disables the filter. See docs/signal_track_record.md.
TRACK_RECORD_ERA_CUTOFF_DATE = os.environ.get(
    "TRACK_RECORD_ERA_CUTOFF_DATE", "2026-08-02"
).strip()


def era_cutoff_prefix() -> str | None:
    """Return YYYY-MM-DD floor for captured_at, or None when era filter is off."""
    raw = (TRACK_RECORD_ERA_CUTOFF_DATE or "").strip()
    if not raw:
        return None
    # Accept full timestamps; compare on date prefix for TEXT captured_at.
    return raw[:10]


class TrackRecordService:
    def __init__(self):
        self.portfolio_service = PortfolioService()

    # ------------------------------------------------------------------ #
    # Evaluation
    # ------------------------------------------------------------------ #
    def evaluate_due(self) -> int:
        """Score every pending capture whose horizon has elapsed. Returns count."""
        user_id = get_current_user_id()
        with get_connection() as conn:
            due = conn.execute(
                """
                SELECT id, symbol, direction, entry_price
                FROM signal_outcomes
                WHERE user_id = %s AND outcome IS NULL AND eval_due_at <= app_now_text()
                """,
                (user_id,),
            ).fetchall()
            if not due:
                return 0

            price_map = self._price_map()
            evaluated = 0
            for row in due:
                price = price_map.get(row["symbol"])
                if not price or price <= 0:
                    continue  # leave pending until a price is available
                if self._score_row(
                    conn,
                    user_id=user_id,
                    row_id=int(row["id"]),
                    direction=row["direction"],
                    entry_price=float(row["entry_price"]),
                    eval_price=float(price),
                ):
                    evaluated += 1
            if evaluated:
                conn.commit()
            return evaluated

    def reconcile_recommendation_episodes(self) -> int:
        """Apply SAI episode boundaries to pending and already-scored recommendation bets.

        For each symbol, when a later recommendation capture has a different action
        label, the earlier episode is scored (or re-scored) using the later row's
        entry_price as the flip price. Returns the number of rows updated.
        """
        user_id = get_current_user_id()
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, symbol, label, direction, entry_price, outcome,
                       eval_price, return_pct, captured_at
                FROM signal_outcomes
                WHERE user_id = %s AND kind = 'recommendation'
                ORDER BY symbol ASC, captured_at ASC, id ASC
                """,
                (user_id,),
            ).fetchall()
            if not rows:
                return 0

            by_symbol: dict[str, list] = {}
            for row in rows:
                by_symbol.setdefault(row["symbol"], []).append(row)

            updated = 0
            for symbol_rows in by_symbol.values():
                for earlier_id, flip in episode_flip_targets(symbol_rows):
                    earlier = next(r for r in symbol_rows if int(r["id"]) == earlier_id)
                    flip_price = float(flip["entry_price"])
                    if flip_price <= 0:
                        continue
                    entry = float(earlier["entry_price"])
                    if entry <= 0:
                        continue
                    return_pct = round((flip_price - entry) / entry * 100, 2)
                    outcome = self._classify(earlier["direction"], return_pct)
                    # Skip no-op rewrites (already episode-scored at this flip).
                    if (
                        earlier["outcome"] == outcome
                        and earlier["eval_price"] is not None
                        and abs(float(earlier["eval_price"]) - flip_price) < 1e-6
                        and earlier["return_pct"] is not None
                        and abs(float(earlier["return_pct"]) - return_pct) < 1e-6
                    ):
                        continue
                    evaluated_at = flip["captured_at"]
                    conn.execute(
                        """
                        UPDATE signal_outcomes
                        SET eval_price = %s, return_pct = %s, outcome = %s,
                            evaluated_at = COALESCE(%s, app_now_text()),
                            eval_due_at = LEAST(eval_due_at, COALESCE(%s, eval_due_at))
                        WHERE id = %s AND user_id = %s
                        """,
                        (
                            flip_price,
                            return_pct,
                            outcome,
                            evaluated_at,
                            evaluated_at,
                            earlier_id,
                            user_id,
                        ),
                    )
                    updated += 1
            if updated:
                conn.commit()
            return updated

    def early_close_conflicting_recommendations(
        self,
        conn,
        user_id: int,
        symbol: str,
        *,
        new_label: str,
        eval_price: float,
        evaluated_at: str | None = None,
    ) -> int:
        """Close pending recommendation episodes that conflict with a new action.

        Called from assessment capture before inserting the new recommendation bet.
        Soft-closes buy/sell → watch/hold as well (any label change).
        """
        if not eval_price or eval_price <= 0:
            return 0
        pending = conn.execute(
            """
            SELECT id, label, direction, entry_price
            FROM signal_outcomes
            WHERE user_id = %s AND symbol = %s AND kind = 'recommendation'
              AND outcome IS NULL
            """,
            (user_id, symbol),
        ).fetchall()
        closed = 0
        for row in pending:
            if str(row["label"]).lower() == str(new_label).lower():
                continue  # same-action episode continues (dedup skips insert)
            if self._score_row(
                conn,
                user_id=user_id,
                row_id=int(row["id"]),
                direction=row["direction"],
                entry_price=float(row["entry_price"]),
                eval_price=float(eval_price),
                evaluated_at=evaluated_at,
            ):
                closed += 1
        return closed

    def _score_row(
        self,
        conn,
        *,
        user_id: int,
        row_id: int,
        direction: str,
        entry_price: float,
        eval_price: float,
        evaluated_at: str | None = None,
    ) -> bool:
        if not entry_price or entry_price <= 0 or not eval_price or eval_price <= 0:
            return False
        return_pct = round((eval_price - entry_price) / entry_price * 100, 2)
        outcome = self._classify(direction, return_pct)
        if evaluated_at:
            conn.execute(
                """
                UPDATE signal_outcomes
                SET eval_price = %s, return_pct = %s, outcome = %s,
                    evaluated_at = %s,
                    eval_due_at = LEAST(eval_due_at, %s)
                WHERE id = %s AND user_id = %s
                """,
                (
                    eval_price,
                    return_pct,
                    outcome,
                    evaluated_at,
                    evaluated_at,
                    row_id,
                    user_id,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE signal_outcomes
                SET eval_price = %s, return_pct = %s, outcome = %s,
                    evaluated_at = app_now_text()
                WHERE id = %s AND user_id = %s
                """,
                (eval_price, return_pct, outcome, row_id, user_id),
            )
        return True

    @staticmethod
    def _classify(direction: str, return_pct: float) -> str:
        band = TRACK_RECORD_BAND_PCT
        if direction == "bullish":
            if return_pct >= band:
                return "win"
            if return_pct <= -band:
                return "loss"
            return "neutral"
        if direction == "bearish":
            if return_pct <= -band:
                return "win"
            if return_pct >= band:
                return "loss"
            return "neutral"
        # Neutral-direction signals (hold/watch) have no directional bet; we record
        # the realized move but never count them as win/loss.
        return "neutral"

    def _price_map(self) -> dict[str, float]:
        out: dict[str, float] = {}
        try:
            for item in self.portfolio_service.list_symbols():
                price = item.get("currentPrice")
                if price:
                    out[item["symbol"]] = float(price)
        except Exception as exc:  # noqa: BLE001 - best-effort pricing
            logging.warning("Track record price map failed: %s", exc)
        return out

    def capture_fib_proximity_bet(
        self,
        *,
        user_id: int,
        symbol: str,
        entry_price: float,
        label: str,
        direction: str,
        alert_id: int | None = None,
    ) -> bool:
        """Insert a pending Fib proximity bet if none is already open for this label."""
        if not entry_price or entry_price <= 0 or not label:
            return False
        symbol = str(symbol).upper()
        with get_connection() as conn:
            pending = conn.execute(
                """
                SELECT 1 FROM signal_outcomes
                WHERE user_id = %s AND symbol = %s AND kind = 'fib' AND label = %s
                  AND outcome IS NULL
                LIMIT 1
                """,
                (user_id, symbol, label),
            ).fetchone()
            if pending is not None:
                return False
            conn.execute(
                """
                INSERT INTO signal_outcomes (
                    user_id, symbol, kind, label, direction,
                    entry_price, horizon_days, eval_due_at, alert_id
                )
                VALUES (
                    %s, %s, 'fib', %s, %s, %s, %s,
                    to_char(
                        timezone('UTC', now()) + (%s || ' days')::interval,
                        'YYYY-MM-DD HH24:MI:SS'
                    ),
                    %s
                )
                """,
                (
                    user_id,
                    symbol,
                    label,
                    direction,
                    float(entry_price),
                    TRACK_RECORD_HORIZON_DAYS,
                    TRACK_RECORD_HORIZON_DAYS,
                    alert_id,
                ),
            )
            conn.commit()
        return True

    def backfill_recommendation_strength(self) -> int:
        """Copy confidence / Fit / band from assessments onto recommendation bets missing them.

        Runs on Summary load so post-era SAI rows get Conf·Score for Bet-S-Hit.
        Pre-era rows may also be filled, but ``get_summary`` excludes them from
        aggregates (filter-in-query; no mass delete).
        """
        user_id = get_current_user_id()
        with get_connection() as conn:
            # Link orphan recommendation bets to the nearest prior assessment.
            conn.execute(
                """
                UPDATE signal_outcomes so
                SET assessment_id = sub.aid
                FROM (
                    SELECT so2.id AS sid,
                           (
                             SELECT a.id
                             FROM assessments a
                             WHERE a.user_id = so2.user_id
                               AND a.symbol = so2.symbol
                               AND a.created_at <= so2.captured_at
                             ORDER BY a.created_at DESC, a.id DESC
                             LIMIT 1
                           ) AS aid
                    FROM signal_outcomes so2
                    WHERE so2.user_id = %s
                      AND so2.kind = 'recommendation'
                      AND so2.assessment_id IS NULL
                ) sub
                WHERE so.id = sub.sid AND sub.aid IS NOT NULL
                """,
                (user_id,),
            )
            rows = conn.execute(
                """
                SELECT so.id, so.assessment_id, a.confidence, a.trading_recommendation
                FROM signal_outcomes so
                JOIN assessments a ON a.id = so.assessment_id
                WHERE so.user_id = %s AND so.kind = 'recommendation'
                  AND so.assessment_id IS NOT NULL
                  AND (
                    so.confidence IS NULL
                    OR so.fit_total IS NULL
                    OR so.band_code IS NULL
                  )
                """,
                (user_id,),
            ).fetchall()
            updated = 0
            for row in rows:
                confidence, fit_total, band_code = strength_from_assessment_row(row)
                if confidence is None and fit_total is None and band_code is None:
                    continue
                conn.execute(
                    """
                    UPDATE signal_outcomes
                    SET confidence = COALESCE(confidence, %s),
                        fit_total = COALESCE(fit_total, %s),
                        band_code = COALESCE(band_code, %s)
                    WHERE id = %s AND user_id = %s
                    """,
                    (confidence, fit_total, band_code, int(row["id"]), user_id),
                )
                updated += 1
            conn.commit()
            return updated

    # ------------------------------------------------------------------ #
    # Reporting
    # ------------------------------------------------------------------ #
    def get_summary(self) -> dict[str, Any]:
        """Reconcile SAI episodes, backfill strength, evaluate due, aggregate.

        Aggregates only outcomes on/after ``eraCutoffDate`` (filter-in-query).
        Pre-era rows remain in the DB for audit but do not dilute Hit / Bet-S-Hit
        or proposal soft-weights that consume this summary.
        """
        self.reconcile_recommendation_episodes()
        self.backfill_recommendation_strength()
        self.evaluate_due()
        user_id = get_current_user_id()
        cutoff = era_cutoff_prefix()
        with get_connection() as conn:
            era_clause = ""
            era_params: list[Any] = [user_id]
            if cutoff:
                era_clause = " AND captured_at >= %s"
                era_params.append(cutoff)
            rows = conn.execute(
                f"""
                SELECT kind, label, direction, outcome, return_pct,
                       confidence, fit_total, band_code, sentiment,
                       confluence_band, confluence_score, agree_count,
                       conflict_count, signal_strength
                FROM signal_outcomes
                WHERE user_id = %s AND outcome IS NOT NULL
                {era_clause}
                """,
                tuple(era_params),
            ).fetchall()
            pending = conn.execute(
                f"""
                SELECT COUNT(*) AS n FROM signal_outcomes
                WHERE user_id = %s AND outcome IS NULL
                {era_clause}
                """,
                tuple(era_params),
            ).fetchone()["n"]
            excluded_pre_era = 0
            if cutoff:
                excluded_pre_era = conn.execute(
                    """
                    SELECT COUNT(*) AS n FROM signal_outcomes
                    WHERE user_id = %s AND captured_at < %s
                    """,
                    (user_id, cutoff),
                ).fetchone()["n"]

        overall = _new_bucket()
        by_kind: dict[str, dict[str, Any]] = {}
        by_label: dict[tuple[str, str], dict[str, Any]] = {}
        by_confidence: dict[str, dict[str, Any]] = {}
        by_fit_band: dict[str, dict[str, Any]] = {}
        by_confluence_band: dict[str, dict[str, Any]] = {}
        by_confluence_conflict: dict[str, dict[str, Any]] = {}
        for row in rows:
            _accumulate(overall, row)
            kind_bucket = by_kind.setdefault(row["kind"], _new_bucket())
            _accumulate(kind_bucket, row)
            label_key = (row["kind"], row["label"])
            label_bucket = by_label.setdefault(
                label_key,
                {**_new_bucket(), "kind": row["kind"], "label": row["label"], "direction": row["direction"]},
            )
            _accumulate(label_bucket, row)

            if row["kind"] == "recommendation":
                conf_key = (str(row["confidence"] or "unknown").strip().lower() or "unknown")
                conf_bucket = by_confidence.setdefault(
                    conf_key, {**_new_bucket(), "confidence": conf_key}
                )
                _accumulate(conf_bucket, row)
                fit_key = fit_band_label(row["fit_total"])
                fit_bucket = by_fit_band.setdefault(
                    fit_key, {**_new_bucket(), "fitBand": fit_key}
                )
                _accumulate(fit_bucket, row)

            if row["kind"] == "confluence":
                band_key = (
                    str(row.get("confluence_band") or "unknown").strip().lower() or "unknown"
                )
                band_bucket = by_confluence_band.setdefault(
                    band_key, {**_new_bucket(), "confluenceBand": band_key}
                )
                _accumulate(band_bucket, row)
                conflict_key = conflict_bucket_label(row.get("conflict_count"))
                conflict_bucket = by_confluence_conflict.setdefault(
                    conflict_key, {**_new_bucket(), "conflictBucket": conflict_key}
                )
                _accumulate(conflict_bucket, row)

        return {
            "horizonDays": TRACK_RECORD_HORIZON_DAYS,
            "horizonBandPct": TRACK_RECORD_BAND_PCT,
            "eraCutoffDate": cutoff,
            "excludedPreEra": excluded_pre_era,
            "pending": pending,
            "overall": _finalize(overall),
            "byKind": {kind: _finalize(bucket) for kind, bucket in by_kind.items()},
            "byLabel": sorted(
                (_finalize(bucket) for bucket in by_label.values()),
                key=lambda b: (b["kind"], -b["count"], b["label"]),
            ),
            "byConfidence": sorted(
                (_finalize(bucket) for bucket in by_confidence.values()),
                key=lambda b: _confidence_sort_key(b.get("confidence")),
            ),
            "byFitBand": sorted(
                (_finalize(bucket) for bucket in by_fit_band.values()),
                key=lambda b: _fit_band_sort_key(b.get("fitBand")),
            ),
            "byConfluenceBand": sorted(
                (_finalize(bucket) for bucket in by_confluence_band.values()),
                key=lambda b: _confluence_band_sort_key(b.get("confluenceBand")),
            ),
            "byConfluenceConflict": sorted(
                (_finalize(bucket) for bucket in by_confluence_conflict.values()),
                key=lambda b: _conflict_bucket_sort_key(b.get("conflictBucket")),
            ),
        }


def episode_flip_targets(rows: list[Any]) -> list[tuple[int, Any]]:
    """Pair each recommendation row with the next differently labeled capture.

    ``rows`` must be ordered by captured_at, id ascending for one symbol.
    Returns (earlier_row_id, flip_row) pairs.
    """
    pairs: list[tuple[int, Any]] = []
    for index, row in enumerate(rows):
        label = str(row["label"]).lower()
        for later in rows[index + 1 :]:
            if str(later["label"]).lower() != label:
                pairs.append((int(row["id"]), later))
                break
    return pairs


def strength_from_assessment_row(row) -> tuple[str | None, float | None, str | None]:
    """Parse confidence / Fit total / band code from an assessment join row."""
    try:
        confidence = row["confidence"]
    except (KeyError, TypeError, IndexError):
        confidence = None
    confidence = str(confidence).strip().lower() if confidence else None
    if confidence not in ("high", "medium", "low"):
        confidence = None

    fit_total = None
    band_code = None
    try:
        raw = row["trading_recommendation"]
    except (KeyError, TypeError, IndexError):
        raw = None
    if raw:
        try:
            proposal = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError, json.JSONDecodeError):
            proposal = None
        if isinstance(proposal, dict):
            scores = proposal.get("scores") or {}
            if scores.get("total") is not None:
                try:
                    fit_total = round(float(scores["total"]), 2)
                except (TypeError, ValueError):
                    fit_total = None
            band = proposal.get("bandBias") or {}
            code = band.get("code")
            if code:
                band_code = str(code).strip()
    return confidence, fit_total, band_code


def strength_from_proposal(proposal: dict[str, Any] | None, confidence: str | None) -> tuple[str | None, float | None, str | None]:
    conf = str(confidence or "").strip().lower() or None
    if conf not in ("high", "medium", "low"):
        conf = None
    fit_total = None
    band_code = None
    if isinstance(proposal, dict):
        scores = proposal.get("scores") or {}
        if scores.get("total") is not None:
            try:
                fit_total = round(float(scores["total"]), 2)
            except (TypeError, ValueError):
                fit_total = None
        band = proposal.get("bandBias") or {}
        if band.get("code"):
            band_code = str(band["code"]).strip()
        if not conf:
            pub = str(proposal.get("confidence") or "").strip().lower()
            if pub in ("high", "medium", "low"):
                conf = pub
    return conf, fit_total, band_code


def confluence_outcome_meta(confluence: dict[str, Any] | None) -> dict[str, Any]:
    """Lean/Strong band, score, agree/conflict counts, and conviction strength.

    Label on the bet stays Bullish/Bearish for scoring continuity; ``confluenceBand``
    carries whether the fuse was Lean (±0.15) or Strong (±0.45).
    """
    block = confluence if isinstance(confluence, dict) else {}
    bias = str(block.get("bias") or "").strip()
    bias_l = bias.lower()
    band = None
    if "lean" in bias_l:
        band = "lean"
    elif "bull" in bias_l or "bear" in bias_l:
        band = "strong"

    score = None
    if block.get("score") is not None:
        try:
            score = round(float(block["score"]), 3)
        except (TypeError, ValueError):
            score = None

    agree = None
    if block.get("agreeCount") is not None:
        try:
            agree = int(block["agreeCount"])
        except (TypeError, ValueError):
            agree = None

    conflict = None
    if block.get("conflictCount") is not None:
        try:
            conflict = int(block["conflictCount"])
        except (TypeError, ValueError):
            conflict = None

    strength = str(block.get("strength") or "").strip().lower() or None
    if strength not in ("strong", "moderate", "weak"):
        strength = None

    return {
        "confluenceBand": band,
        "confluenceScore": score,
        "agreeCount": agree,
        "conflictCount": conflict,
        "signalStrength": strength,
    }


def conflict_bucket_label(conflict_count: int | None) -> str:
    if conflict_count is None:
        return "unknown"
    return "clean" if int(conflict_count) <= 0 else "contested"


def fit_band_label(fit_total: float | None) -> str:
    """Raw SAI Score band — same High/Medium/Low cuts as Conf base (no softening)."""
    from services.proposal_service import score_band_for_total

    return score_band_for_total(fit_total)


def _confidence_weight(confidence: str | None) -> float:
    return {"high": 3.0, "medium": 2.0, "low": 1.0}.get(str(confidence or "").lower(), 1.0)


def _fit_weight(fit_total: float | None) -> float:
    if fit_total is None:
        return 1.0
    # Scale 0–100 Fit into roughly 1.0–2.0 so high Fit failures weigh more.
    return 1.0 + max(0.0, min(float(fit_total), 100.0)) / 100.0


def _confidence_sort_key(confidence: str | None) -> tuple:
    order = {"high": 0, "medium": 1, "low": 2, "unknown": 3}
    key = str(confidence or "unknown").lower()
    return (order.get(key, 9), key)


def _fit_band_sort_key(fit_band: str | None) -> tuple:
    # Same vocabulary as Conf (high/medium/low); legacy strong/mid/weak sort as aliases.
    order = {
        "high": 0,
        "strong": 0,
        "medium": 1,
        "mid": 1,
        "low": 2,
        "weak": 2,
        "unknown": 3,
    }
    key = str(fit_band or "unknown").lower()
    return (order.get(key, 9), key)


def _confluence_band_sort_key(band: str | None) -> tuple:
    order = {"strong": 0, "lean": 1, "unknown": 2}
    key = str(band or "unknown").lower()
    return (order.get(key, 9), key)


def _conflict_bucket_sort_key(bucket: str | None) -> tuple:
    order = {"clean": 0, "contested": 1, "unknown": 2}
    key = str(bucket or "unknown").lower()
    return (order.get(key, 9), key)


def _new_bucket() -> dict[str, Any]:
    return {
        "count": 0,
        "wins": 0,
        "losses": 0,
        "neutrals": 0,
        "_return_sum": 0.0,
        "_adj_return_sum": 0.0,
        "_weight_win": 0.0,
        "_weight_decided": 0.0,
    }


def _direction_adjusted_return(direction: str | None, return_pct: float | None) -> float | None:
    if return_pct is None:
        return None
    value = float(return_pct)
    direction = str(direction or "").lower()
    if direction == "bearish":
        return -value
    if direction == "bullish":
        return value
    return 0.0


def _accumulate(bucket: dict[str, Any], row) -> None:
    bucket["count"] += 1
    outcome = row["outcome"]
    if outcome == "win":
        bucket["wins"] += 1
    elif outcome == "loss":
        bucket["losses"] += 1
    else:
        bucket["neutrals"] += 1
    if row["return_pct"] is not None:
        bucket["_return_sum"] += float(row["return_pct"])
    adj = _direction_adjusted_return(row["direction"], row["return_pct"])
    if adj is not None:
        bucket["_adj_return_sum"] += adj

    confidence = row["confidence"] if "confidence" in row.keys() else None
    fit_total = row["fit_total"] if "fit_total" in row.keys() else None
    weight = _confidence_weight(confidence) * _fit_weight(fit_total)
    if outcome in ("win", "loss"):
        bucket["_weight_decided"] += weight
        if outcome == "win":
            bucket["_weight_win"] += weight


def _finalize(bucket: dict[str, Any]) -> dict[str, Any]:
    decided = bucket["wins"] + bucket["losses"]
    hit_rate = round(bucket["wins"] / decided * 100, 1) if decided else None
    avg_return = round(bucket["_return_sum"] / bucket["count"], 2) if bucket["count"] else None
    avg_return_adj = (
        round(bucket["_adj_return_sum"] / bucket["count"], 2) if bucket["count"] else None
    )
    calibrated = None
    if bucket["_weight_decided"] > 0:
        calibrated = round(bucket["_weight_win"] / bucket["_weight_decided"] * 100, 1)
    out = {k: v for k, v in bucket.items() if not k.startswith("_")}
    out["hitRate"] = hit_rate
    out["avgReturn"] = avg_return
    out["avgReturnAdj"] = avg_return_adj
    out["calibratedHitRate"] = calibrated
    return out
