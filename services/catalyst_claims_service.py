"""Durable forward-looking catalyst / watch-out claims (slice A) and evaluation (B).

Claims are captured from note-synthesis ``catalystsToWatch`` and live outside the
trimmed assessment history. Evaluation (B) and the SAI scorecard (C/D) are gated:
if a symbol has no claims, those paths are no-ops and leave existing SAI/UI alone.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
import hashlib
import json
import logging
import re
from typing import Any

from db.database import get_connection, get_current_user_id

VALID_STATUSES = frozenset(
    {"open", "substantiated", "missed", "revised", "inconclusive"}
)
VALID_DIRECTIONS = frozenset({"above", "below", "unknown"})

# Human metric phrases -> fundamentals / growth keys we can auto-score.
_METRIC_KEY_ALIASES: tuple[tuple[str, str], ...] = (
    ("revenue growth", "revenueGrowth"),
    ("sales growth", "revenueGrowth"),
    ("yoy revenue", "revenueGrowth"),
    ("earnings growth", "earningsGrowth"),
    ("eps growth", "earningsGrowth"),
    ("gross margin", "grossMargin"),
    ("operating margin", "operatingMargin"),
    ("ebitda margin", "ebitdaMargin"),
    ("profit margin", "profitMargin"),
    ("net margin", "profitMargin"),
    ("roe", "returnOnEquity"),
    ("return on equity", "returnOnEquity"),
    ("arr", "arr"),
    ("backlog", "backlog"),
    ("free cash flow", "freeCashflow"),
    ("fcf", "freeCashflow"),
)

_NUM_RE = re.compile(
    r"(?P<sign>[+-])?\s*(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>%|bps|x)?",
    re.IGNORECASE,
)

# Age-out policy: after due period + grace (or max open age), stop re-eval and close.
_AGEOUT_GRACE_MONTHS = 6
_AGEOUT_MAX_OPEN_MONTHS = 24
_SCORECARD_CLOSED_VISIBLE_MONTHS = 12

_SEASON_END_MONTH = {
    "spring": 6,
    "summer": 9,
    "fall": 12,
    "autumn": 12,
    "winter": 3,
}


class CatalystClaimsService:
    """Capture durable watch-out claims and evaluate them when reality updates."""

    # ------------------------------------------------------------------ #
    # Gate
    # ------------------------------------------------------------------ #
    def has_claims(self, symbol: str) -> bool:
        symbol = symbol.upper()
        user_id = get_current_user_id()
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM catalyst_claims
                WHERE user_id = %s AND symbol = %s
                LIMIT 1
                """,
                (user_id, symbol),
            ).fetchone()
        return row is not None

    def has_open_claims(self, symbol: str) -> bool:
        symbol = symbol.upper()
        user_id = get_current_user_id()
        with get_connection() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM catalyst_claims
                WHERE user_id = %s AND symbol = %s AND status = 'open'
                LIMIT 1
                """,
                (user_id, symbol),
            ).fetchone()
        return row is not None

    # ------------------------------------------------------------------ #
    # Slice A — capture
    # ------------------------------------------------------------------ #
    def capture_from_synthesis(
        self,
        symbol: str,
        note_id: int | None,
        synthesis: dict[str, Any] | None,
        *,
        also_symbols: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Upsert claims from ``catalystsToWatch``. Returns stamped catalyst rows.

        Stamps ``claimId`` / ``metricKey`` onto the returned catalyst dicts so the
        caller can persist them back onto the note synthesis JSON.
        """
        if not isinstance(synthesis, dict):
            return []
        raw = synthesis.get("catalystsToWatch") or []
        if not isinstance(raw, list) or not raw:
            return []

        targets = self._capture_targets(symbol, also_symbols)
        stamped: list[dict[str, Any]] = []
        user_id = get_current_user_id()

        with get_connection() as conn:
            for item in raw[:8]:
                if not isinstance(item, dict):
                    continue
                normalized = self._normalize_catalyst(item)
                if not normalized:
                    continue
                claim_key = self._claim_key(normalized)
                first_row = None
                for sym in targets:
                    row = self._upsert_claim(
                        conn,
                        user_id=user_id,
                        symbol=sym,
                        note_id=note_id,
                        claim_key=claim_key,
                        catalyst=normalized,
                    )
                    if first_row is None:
                        first_row = row
                if first_row:
                    stamped.append(
                        {
                            **{k: v for k, v in item.items() if k != "claimId"},
                            "period": normalized["period"],
                            "metric": normalized["metric"],
                            "threshold": normalized.get("threshold") or item.get("threshold"),
                            "significance": normalized.get("significance")
                            or item.get("significance"),
                            "metricKey": first_row.get("metric_key")
                            or normalized.get("metricKey"),
                            "claimId": int(first_row["id"]),
                        }
                    )
            conn.commit()
        return stamped

    def stamp_synthesis_catalysts(
        self,
        note_id: int,
        synthesis: dict[str, Any],
        stamped: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Write claim ids back onto the note's synthesis JSON (best-effort)."""
        if not stamped:
            return synthesis
        updated = {**synthesis, "catalystsToWatch": stamped}
        user_id = get_current_user_id()
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE notes
                SET synthesis = %s
                WHERE id = %s AND user_id = %s
                """,
                (json.dumps(updated), note_id, user_id),
            )
            conn.commit()
        return updated

    # ------------------------------------------------------------------ #
    # Slice B — evaluate (gated)
    # ------------------------------------------------------------------ #
    def evaluate_symbol(
        self,
        symbol: str,
        *,
        fundamentals: dict[str, Any] | None = None,
        evidence_notes: list[dict[str, Any]] | None = None,
        llm_client: Any | None = None,
    ) -> dict[str, Any]:
        """Score open claims when evidence is available. No-op if none exist.

        Past-due opens get one last auto pass, then age out as inconclusive.
        They are never sent to the LLM adjudicator.
        """
        symbol = symbol.upper()
        if not self.has_open_claims(symbol):
            return {"evaluated": 0, "skipped": True, "reason": "no_open_claims"}

        open_claims = self.list_claims(symbol, status="open")
        if not open_claims:
            return {"evaluated": 0, "skipped": True, "reason": "no_open_claims"}

        today = date.today()
        active: list[dict[str, Any]] = []
        past_due: list[dict[str, Any]] = []
        for claim in open_claims:
            if self.is_past_due(claim, today=today):
                past_due.append(claim)
            else:
                active.append(claim)

        evidence = self._build_evidence(fundamentals, evidence_notes)
        evaluated = 0
        aged_out = 0
        remaining: list[dict[str, Any]] = []

        # (1)+(2): past-due — final auto attempt, else close; never LLM.
        for claim in past_due:
            verdict = self._auto_verdict(claim, evidence)
            if verdict:
                self._apply_verdict(claim["id"], verdict)
                evaluated += 1
            else:
                self._apply_verdict(
                    claim["id"],
                    {
                        "status": "inconclusive",
                        "observedValue": "",
                        "observedPeriod": claim.get("duePeriod") or claim.get("period") or "",
                        "verdictDetail": (
                            "Period elapsed without a measurable outcome — "
                            "aged out of active watch-outs."
                        ),
                        "evaluationSource": "ageout",
                    },
                )
                aged_out += 1
                evaluated += 1

        for claim in active:
            verdict = self._auto_verdict(claim, evidence)
            if verdict:
                self._apply_verdict(claim["id"], verdict)
                evaluated += 1
            else:
                remaining.append(claim)

        if remaining and llm_client is not None and evidence.get("hasSignal"):
            try:
                llm_verdicts = llm_client.adjudicate_catalyst_claims(
                    symbol, remaining, evidence
                )
            except Exception as exc:  # noqa: BLE001 - never block assess/synth
                logging.warning(
                    "Catalyst claim LLM adjudicate failed for %s: %s", symbol, exc
                )
                llm_verdicts = []
            for item in llm_verdicts or []:
                if not isinstance(item, dict):
                    continue
                claim_id = item.get("claimId") or item.get("id")
                status = str(item.get("status") or "").strip().lower()
                if claim_id is None or status not in VALID_STATUSES or status == "open":
                    continue
                self._apply_verdict(
                    int(claim_id),
                    {
                        "status": status,
                        "observedValue": item.get("observedValue")
                        or item.get("observed_value"),
                        "observedPeriod": item.get("observedPeriod")
                        or item.get("observed_period"),
                        "verdictDetail": item.get("verdictDetail")
                        or item.get("verdict_detail")
                        or item.get("detail")
                        or "",
                        "evaluationSource": "llm",
                        "evidenceNoteId": item.get("evidenceNoteId")
                        or item.get("evidence_note_id"),
                    },
                )
                evaluated += 1

        return {
            "evaluated": evaluated,
            "agedOut": aged_out,
            "skipped": False,
            "openRemaining": self.has_open_claims(symbol),
        }

    # ------------------------------------------------------------------ #
    # Slice C — scorecard (gated)
    # ------------------------------------------------------------------ #
    def scorecard(self, symbol: str) -> dict[str, Any] | None:
        """Build a SAI scorecard. Returns None when no claims exist (UI undisturbed).

        (3) UI age-out: show still-current opens + recently closed only.
        Past-due opens are treated as archived for display until evaluate closes them.
        """
        claims = self.list_claims(symbol)
        if not claims:
            return None

        today = date.today()
        visible: list[dict[str, Any]] = []
        archived_count = 0
        for claim in claims:
            if self._scorecard_visible(claim, today=today):
                visible.append(claim)
            else:
                archived_count += 1

        if not visible and archived_count:
            return {
                "summary": (
                    f"{archived_count} prior watch-out(s) archived "
                    "(period elapsed or closed earlier)."
                ),
                "openCount": 0,
                "closedCount": 0,
                "archivedCount": archived_count,
                "items": [],
            }
        if not visible:
            return None

        items = []
        open_count = 0
        closed_count = 0
        for claim in visible[:12]:
            status = claim["status"]
            if status == "open":
                open_count += 1
            else:
                closed_count += 1
            items.append(
                {
                    "id": claim["id"],
                    "period": claim["period"],
                    "metric": claim["metric"],
                    "metricKey": claim.get("metricKey"),
                    "threshold": claim.get("threshold") or "",
                    "significance": claim.get("significance") or "",
                    "status": status,
                    "observedValue": claim.get("observedValue") or "",
                    "observedPeriod": claim.get("observedPeriod") or "",
                    "verdictDetail": claim.get("verdictDetail") or "",
                    "capturedAt": claim.get("capturedAt"),
                    "evaluatedAt": claim.get("evaluatedAt"),
                }
            )

        substantiated = sum(1 for c in visible if c["status"] == "substantiated")
        missed = sum(1 for c in visible if c["status"] == "missed")
        parts = []
        if substantiated:
            parts.append(f"{substantiated} substantiated")
        if missed:
            parts.append(f"{missed} missed")
        if open_count:
            parts.append(f"{open_count} still open")
        if archived_count:
            parts.append(f"{archived_count} archived")
        summary = (
            f"Prior watch-outs: {', '.join(parts)}."
            if parts
            else f"{len(visible)} prior watch-out(s) on record."
        )

        return {
            "summary": summary,
            "openCount": open_count,
            "closedCount": closed_count,
            "archivedCount": archived_count,
            "items": items,
        }

    def list_claims(
        self, symbol: str, status: str | None = None, limit: int = 40
    ) -> list[dict[str, Any]]:
        symbol = symbol.upper()
        user_id = get_current_user_id()
        query = """
            SELECT id, user_id, symbol, note_id, claim_key, period, metric, metric_key,
                   threshold, significance, direction, status, captured_at, due_period,
                   evaluated_at, observed_value, observed_period, evidence_note_id,
                   verdict_detail, evaluation_source
            FROM catalyst_claims
            WHERE user_id = %s AND symbol = %s
        """
        params: list[Any] = [user_id, symbol]
        if status:
            query += " AND status = %s"
            params.append(status)
        query += " ORDER BY captured_at DESC, id DESC LIMIT %s"
        params.append(limit)
        with get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_claim(row) for row in rows]


    # ------------------------------------------------------------------ #
    # Age-out helpers
    # ------------------------------------------------------------------ #
    @classmethod
    def is_past_due(cls, claim: dict[str, Any], *, today: date | None = None) -> bool:
        """True when the claim's outlook window (+ grace) has elapsed."""
        today = today or date.today()
        period_text = str(claim.get("duePeriod") or claim.get("period") or "")
        period_end = cls.parse_period_end(period_text)
        if period_end is not None:
            return today > cls._add_months(period_end, _AGEOUT_GRACE_MONTHS)
        captured = cls._parse_date(claim.get("capturedAt"))
        if captured is None:
            return False
        return today > cls._add_months(captured, _AGEOUT_MAX_OPEN_MONTHS)

    @classmethod
    def _scorecard_visible(cls, claim: dict[str, Any], *, today: date) -> bool:
        status = str(claim.get("status") or "").lower()
        if status == "open":
            # Hide past-due opens from the live list (still in DB until evaluate ages them).
            return not cls.is_past_due(claim, today=today)
        # Closed: keep recently resolved ones visible.
        closed_at = cls._parse_date(claim.get("evaluatedAt")) or cls._parse_date(
            claim.get("capturedAt")
        )
        if closed_at is None:
            return True
        return today <= cls._add_months(closed_at, _SCORECARD_CLOSED_VISIBLE_MONTHS)

    @staticmethod
    def parse_period_end(text: str) -> date | None:
        """Best-effort end date for a claim period label."""
        raw = (text or "").strip().lower()
        if not raw or raw in {"upcoming", "near term", "near-term", "ttm", "n/a"}:
            return None

        # Q1 2026 / 2026 Q1 / fiscal Q2 2027
        m = re.search(r"(?:fy|fiscal\s*)?q([1-4])\s*(?:fy|fiscal\s*)?(20\d{2})", raw)
        if not m:
            m = re.search(r"(20\d{2})\s*(?:fy|fiscal\s*)?q([1-4])", raw)
            if m:
                year, q = int(m.group(1)), int(m.group(2))
            else:
                year = q = None  # type: ignore[assignment]
        else:
            q, year = int(m.group(1)), int(m.group(2))
        if year and q:
            end_month = q * 3
            # last day of quarter month
            if end_month == 12:
                return date(year, 12, 31)
            nxt = date(year, end_month + 1, 1)
            return nxt - timedelta(days=1)

        # H1 / H2 2026
        m = re.search(r"h([12])\s*(20\d{2})", raw)
        if m:
            half, year = int(m.group(1)), int(m.group(2))
            end_month = 6 if half == 1 else 12
            if end_month == 12:
                return date(year, 12, 31)
            return date(year, 7, 1) - timedelta(days=1)

        # Spring/Summer/Fall/Winter 2027
        m = re.search(
            r"(spring|summer|fall|autumn|winter)\s*(20\d{2})",
            raw,
        )
        if m:
            season, year = m.group(1), int(m.group(2))
            month = _SEASON_END_MONTH[season]
            if season == "winter":
                # Winter 2027 ~= end of Mar 2027
                return date(year, 3, 31)
            if month == 12:
                return date(year, 12, 31)
            return date(year, month + 1, 1) - timedelta(days=1)

        # Fiscal 2027 / FY2027 / FY 2027
        m = re.search(r"(?:fy|fiscal)\s*(20\d{2})", raw)
        if m:
            year = int(m.group(1))
            return date(year, 12, 31)

        # Bare year
        m = re.search(r"\b(20\d{2})\b", raw)
        if m:
            return date(int(m.group(1)), 12, 31)

        return None

    @staticmethod
    def _parse_date(value: Any) -> date | None:
        if value is None:
            return None
        if isinstance(value, date) and not isinstance(value, datetime):
            return value
        if isinstance(value, datetime):
            return value.date()
        text = str(value).strip()
        if not text:
            return None
        text = text.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(text[:32]).date()
        except ValueError:
            pass
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return None

    @staticmethod
    def _add_months(start: date, months: int) -> date:
        year = start.year + (start.month - 1 + months) // 12
        month = (start.month - 1 + months) % 12 + 1
        if month == 12:
            last = date(year, 12, 31)
        else:
            last = date(year, month + 1, 1) - timedelta(days=1)
        day = min(start.day, last.day)
        return date(year, month, day)

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    @staticmethod
    def _capture_targets(symbol: str, also_symbols: list[str] | None) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for raw in [symbol, *(also_symbols or [])]:
            sym = str(raw or "").strip().upper()
            if not sym or sym in seen:
                continue
            seen.add(sym)
            out.append(sym)
        return out

    def _normalize_catalyst(self, item: dict[str, Any]) -> dict[str, Any] | None:
        period = str(item.get("period") or "").strip() or "Upcoming"
        metric = str(item.get("metric") or "").strip()
        if not metric:
            return None
        threshold = str(item.get("threshold") or "").strip()
        significance = str(item.get("significance") or "").strip()
        metric_key = str(item.get("metricKey") or item.get("metric_key") or "").strip()
        if not metric_key:
            metric_key = self.infer_metric_key(metric) or ""
        direction = str(item.get("direction") or "").strip().lower()
        if direction not in VALID_DIRECTIONS:
            direction = self._infer_direction(threshold)
        return {
            "period": period[:80],
            "metric": metric[:160],
            "metricKey": metric_key[:64] or None,
            "threshold": threshold[:120] or None,
            "significance": significance[:400] or None,
            "direction": direction,
            "duePeriod": period[:80],
        }

    @staticmethod
    def _claim_key(catalyst: dict[str, Any]) -> str:
        raw = "|".join(
            [
                str(catalyst.get("period") or "").lower().strip(),
                str(catalyst.get("metric") or "").lower().strip(),
                str(catalyst.get("threshold") or "").lower().strip(),
            ]
        )
        raw = re.sub(r"\s+", " ", raw)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]

    def _upsert_claim(
        self,
        conn,
        *,
        user_id: int,
        symbol: str,
        note_id: int | None,
        claim_key: str,
        catalyst: dict[str, Any],
    ) -> dict[str, Any]:
        existing = conn.execute(
            """
            SELECT id, status, metric_key FROM catalyst_claims
            WHERE user_id = %s AND symbol = %s AND claim_key = %s
            """,
            (user_id, symbol, claim_key),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE catalyst_claims
                SET period = %s,
                    metric = %s,
                    metric_key = COALESCE(%s, metric_key),
                    threshold = %s,
                    significance = %s,
                    direction = %s,
                    due_period = %s,
                    note_id = COALESCE(%s, note_id)
                WHERE id = %s
                """,
                (
                    catalyst["period"],
                    catalyst["metric"],
                    catalyst.get("metricKey"),
                    catalyst.get("threshold"),
                    catalyst.get("significance"),
                    catalyst["direction"],
                    catalyst.get("duePeriod") or catalyst["period"],
                    note_id,
                    existing["id"],
                ),
            )
            row = conn.execute(
                "SELECT * FROM catalyst_claims WHERE id = %s",
                (existing["id"],),
            ).fetchone()
            return dict(row)

        row = conn.execute(
            """
            INSERT INTO catalyst_claims (
                user_id, symbol, note_id, claim_key, period, metric, metric_key,
                threshold, significance, direction, due_period, status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'open')
            RETURNING *
            """,
            (
                user_id,
                symbol,
                note_id,
                claim_key,
                catalyst["period"],
                catalyst["metric"],
                catalyst.get("metricKey"),
                catalyst.get("threshold"),
                catalyst.get("significance"),
                catalyst["direction"],
                catalyst.get("duePeriod") or catalyst["period"],
            ),
        ).fetchone()
        return dict(row)

    def _apply_verdict(self, claim_id: int, verdict: dict[str, Any]) -> None:
        status = str(verdict.get("status") or "").strip().lower()
        if status not in VALID_STATUSES or status == "open":
            return
        user_id = get_current_user_id()
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE catalyst_claims
                SET status = %s,
                    evaluated_at = app_now_text(),
                    observed_value = %s,
                    observed_period = %s,
                    verdict_detail = %s,
                    evaluation_source = %s,
                    evidence_note_id = %s
                WHERE id = %s AND user_id = %s AND status = 'open'
                """,
                (
                    status,
                    (str(verdict.get("observedValue") or "").strip() or None),
                    (str(verdict.get("observedPeriod") or "").strip() or None),
                    (str(verdict.get("verdictDetail") or "").strip() or None),
                    verdict.get("evaluationSource") or "auto",
                    verdict.get("evidenceNoteId") or verdict.get("evidence_note_id"),
                    claim_id,
                    user_id,
                ),
            )
            conn.commit()

    def _build_evidence(
        self,
        fundamentals: dict[str, Any] | None,
        evidence_notes: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        flat_metrics: dict[str, Any] = {}
        if isinstance(fundamentals, dict):
            for group in fundamentals.values():
                if isinstance(group, dict):
                    for key, value in group.items():
                        if isinstance(value, (int, float)):
                            flat_metrics[str(key)] = float(value)

        observations: list[dict[str, Any]] = []
        for note in evidence_notes or []:
            if not isinstance(note, dict):
                continue
            synthesis = note.get("synthesis")
            if not isinstance(synthesis, dict):
                continue
            note_id = note.get("id")
            note_date = note.get("date") or note.get("note_date") or ""
            for growth in synthesis.get("growthTrajectory") or []:
                if not isinstance(growth, dict):
                    continue
                observations.append(
                    {
                        "kind": "growth",
                        "metric": str(growth.get("metric") or ""),
                        "metricKey": self.infer_metric_key(str(growth.get("metric") or "")),
                        "valueText": str(growth.get("growth") or ""),
                        "period": str(growth.get("period") or note_date or ""),
                        "noteId": note_id,
                    }
                )
            for proj in synthesis.get("revenueProjections") or []:
                if not isinstance(proj, dict):
                    continue
                observations.append(
                    {
                        "kind": "projection",
                        "metric": str(proj.get("target") or "revenue"),
                        "metricKey": None,
                        "valueText": str(proj.get("target") or ""),
                        "period": str(
                            proj.get("timeline") or proj.get("period") or note_date or ""
                        ),
                        "noteId": note_id,
                    }
                )

        return {
            "fundamentals": flat_metrics,
            "observations": observations,
            "hasSignal": bool(flat_metrics or observations),
            "noteSummaries": [
                {
                    "id": n.get("id"),
                    "date": n.get("date") or n.get("note_date"),
                    "summary": (n.get("synthesis") or {}).get("summary")
                    if isinstance(n.get("synthesis"), dict)
                    else None,
                }
                for n in (evidence_notes or [])
                if isinstance(n, dict) and n.get("synthesis")
            ][:8],
        }

    def _auto_verdict(
        self, claim: dict[str, Any], evidence: dict[str, Any]
    ) -> dict[str, Any] | None:
        threshold = self._parse_threshold(claim.get("threshold") or "")
        metric_key = claim.get("metricKey")
        direction = claim.get("direction") or "above"

        if metric_key and threshold and metric_key in (evidence.get("fundamentals") or {}):
            observed = float(evidence["fundamentals"][metric_key])
            target = threshold["value"]
            unit = threshold.get("unit") or ""
            compare_obs = observed
            if unit == "%" and abs(observed) <= 1.5:
                compare_obs = observed * 100.0
            status = self._compare_status(compare_obs, target, direction)
            if status:
                display = self._format_observed(compare_obs, unit or "%")
                return {
                    "status": status,
                    "observedValue": display,
                    "observedPeriod": "TTM / latest fundamentals",
                    "verdictDetail": (
                        f"Fundamentals {metric_key}={display} vs prior watch "
                        f"{claim.get('threshold')} ({direction})."
                    ),
                    "evaluationSource": "auto",
                }

        claim_metric = str(claim.get("metric") or "").lower()
        claim_period = str(claim.get("period") or "").lower()
        claim_note_id = claim.get("noteId")
        for obs in evidence.get("observations") or []:
            # A note must not score the forward-looking claims it itself created.
            if claim_note_id is not None and obs.get("noteId") == claim_note_id:
                continue
            obs_metric = str(obs.get("metric") or "").lower()
            obs_key = obs.get("metricKey")
            matched = False
            if metric_key and obs_key and metric_key == obs_key:
                matched = True
            elif claim_metric and (
                claim_metric in obs_metric or obs_metric in claim_metric
            ):
                matched = True
            else:
                tokens = [t for t in re.split(r"[^a-z0-9]+", claim_metric) if len(t) > 2]
                if tokens and any(t in obs_metric for t in tokens):
                    matched = True
            if not matched:
                continue

            value_text = str(obs.get("valueText") or "")
            parsed = self._parse_threshold(value_text)
            if not threshold or not parsed:
                continue
            obs_period = str(obs.get("period") or "").lower()
            if claim_period and obs_period:
                claim_tokens = set(re.findall(r"q[1-4]|20\d{2}", claim_period))
                obs_tokens = set(re.findall(r"q[1-4]|20\d{2}", obs_period))
                if claim_tokens and obs_tokens and claim_tokens.isdisjoint(obs_tokens):
                    continue

            status = self._compare_status(parsed["value"], threshold["value"], direction)
            if not status:
                continue
            return {
                "status": status,
                "observedValue": value_text.strip()[:80],
                "observedPeriod": str(obs.get("period") or "")[:80] or None,
                "verdictDetail": (
                    f"Note evidence {value_text.strip()} vs prior watch "
                    f"{claim.get('metric')} {claim.get('threshold')}."
                ),
                "evaluationSource": "auto",
                "evidenceNoteId": obs.get("noteId"),
            }

        return None

    @staticmethod
    def _compare_status(observed: float, target: float, direction: str) -> str | None:
        if direction == "below":
            if observed <= target:
                return "substantiated"
            slack = max(abs(target) * 0.1, 1.0)
            if observed > target + slack:
                return "missed"
            return "inconclusive"
        if direction == "unknown":
            slack = max(abs(target) * 0.1, 1.0)
            if abs(observed - target) <= slack:
                return "substantiated"
            return "inconclusive"
        if observed >= target:
            return "substantiated"
        slack = max(abs(target) * 0.1, 1.0)
        if observed < target - slack:
            return "missed"
        return "inconclusive"

    @staticmethod
    def _format_observed(value: float, unit: str) -> str:
        if unit == "%":
            return f"{value:.1f}%"
        if unit == "bps":
            return f"{value:.0f} bps"
        if unit == "x":
            return f"{value:.2f}x"
        return f"{value:.2f}"

    @staticmethod
    def _parse_threshold(text: str) -> dict[str, Any] | None:
        if not text:
            return None
        match = _NUM_RE.search(text.replace(",", ""))
        if not match:
            return None
        num = float(match.group("num"))
        if match.group("sign") == "-":
            num = -num
        unit = (match.group("unit") or "").lower()
        return {"value": num, "unit": unit}

    @staticmethod
    def _infer_direction(threshold: str) -> str:
        text = (threshold or "").lower()
        if any(tok in text for tok in ("below", "under", "<", "at most", "no more")):
            return "below"
        if any(tok in text for tok in ("above", "over", ">", "+", "at least", ">=")):
            return "above"
        if text.endswith("+") or "%" in text:
            return "above"
        return "unknown"

    @staticmethod
    def infer_metric_key(metric: str) -> str | None:
        text = (metric or "").strip().lower()
        if not text:
            return None
        for needle, key in _METRIC_KEY_ALIASES:
            if needle in text:
                return key
        if re.fullmatch(r"[a-z]+(?:[A-Z][a-z0-9]+)+", metric or ""):
            return metric
        return None

    @staticmethod
    def _row_to_claim(row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "symbol": row["symbol"],
            "noteId": row["note_id"],
            "claimKey": row["claim_key"],
            "period": row["period"],
            "metric": row["metric"],
            "metricKey": row["metric_key"],
            "threshold": row["threshold"],
            "significance": row["significance"],
            "direction": row["direction"],
            "status": row["status"],
            "capturedAt": row["captured_at"],
            "duePeriod": row["due_period"],
            "evaluatedAt": row["evaluated_at"],
            "observedValue": row["observed_value"],
            "observedPeriod": row["observed_period"],
            "evidenceNoteId": row["evidence_note_id"],
            "verdictDetail": row["verdict_detail"],
            "evaluationSource": row["evaluation_source"],
        }
