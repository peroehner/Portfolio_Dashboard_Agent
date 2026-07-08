"""Tier 4: Agent Signal Record — self-scoring for agent signals (recommendations,
patterns, confluence) captured when an assessment run completes.

Each assessment captures a forward-looking "signal outcome" (see
AssessmentService._capture_signal_outcomes). Once the configured horizon elapses,
the evaluator compares the entry price to the current price and labels the bet a
win/loss/neutral based on the signal's direction. The reporting layer aggregates
these into hit rates per recommendation action and per chart pattern.

This is intentionally read-only with respect to future assessments: we measure
the track record but do not yet auto-calibrate (re-weight) future signals.
"""

import logging
import os
from typing import Any

from db.database import get_connection, get_current_user_id
from services.portfolio_service import PortfolioService

# A dead-band so tiny moves do not count as a "win" or "loss". A bullish call
# wins only if the forward return clears +BAND; a bearish call wins only if it
# falls past -BAND; anything inside the band is "neutral".
TRACK_RECORD_BAND_PCT = float(os.environ.get("TRACK_RECORD_BAND_PCT", "2.0"))
TRACK_RECORD_HORIZON_DAYS = max(1, int(os.environ.get("TRACK_RECORD_HORIZON_DAYS", "21")))


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
                entry = row["entry_price"]
                if not entry or entry <= 0:
                    continue
                return_pct = round((price - entry) / entry * 100, 2)
                outcome = self._classify(row["direction"], return_pct)
                conn.execute(
                    """
                    UPDATE signal_outcomes
                    SET eval_price = %s, return_pct = %s, outcome = %s,
                        evaluated_at = app_now_text()
                    WHERE id = %s AND user_id = %s
                    """,
                    (price, return_pct, outcome, row["id"], user_id),
                )
                evaluated += 1
            if evaluated:
                conn.commit()
            return evaluated

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

    # ------------------------------------------------------------------ #
    # Reporting
    # ------------------------------------------------------------------ #
    def get_summary(self) -> dict[str, Any]:
        """Evaluate anything due, then aggregate into hit-rate buckets."""
        self.evaluate_due()
        user_id = get_current_user_id()
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT kind, label, direction, outcome, return_pct
                FROM signal_outcomes
                WHERE user_id = %s AND outcome IS NOT NULL
                """,
                (user_id,),
            ).fetchall()
            pending = conn.execute(
                "SELECT COUNT(*) AS n FROM signal_outcomes WHERE user_id = %s AND outcome IS NULL",
                (user_id,),
            ).fetchone()["n"]

        overall = _new_bucket()
        by_kind: dict[str, dict[str, Any]] = {}
        by_label: dict[tuple[str, str], dict[str, Any]] = {}
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

        return {
            "horizonDays": TRACK_RECORD_HORIZON_DAYS,
            "horizonBandPct": TRACK_RECORD_BAND_PCT,
            "pending": pending,
            "overall": _finalize(overall),
            "byKind": {kind: _finalize(bucket) for kind, bucket in by_kind.items()},
            "byLabel": sorted(
                (_finalize(bucket) for bucket in by_label.values()),
                key=lambda b: (b["kind"], -b["count"], b["label"]),
            ),
        }


def _new_bucket() -> dict[str, Any]:
    return {"count": 0, "wins": 0, "losses": 0, "neutrals": 0, "_return_sum": 0.0}


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


def _finalize(bucket: dict[str, Any]) -> dict[str, Any]:
    decided = bucket["wins"] + bucket["losses"]
    hit_rate = round(bucket["wins"] / decided * 100, 1) if decided else None
    avg_return = round(bucket["_return_sum"] / bucket["count"], 2) if bucket["count"] else None
    out = {k: v for k, v in bucket.items() if not k.startswith("_")}
    out["hitRate"] = hit_rate
    out["avgReturn"] = avg_return
    return out
