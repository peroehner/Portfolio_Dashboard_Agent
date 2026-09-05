"""Weekly Agent Signal Record self-assessment worker.

Once per ISO week (UTC), for each user: score due bets, build Trust/Discount/Use
insight, and persist a snapshot in app_meta. Mirrors the daily assessment gate
pattern in ``daily_assessment_service``.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from db.database import (
    get_connection,
    get_current_user_id,
    list_user_ids,
    reset_current_user_id,
    set_current_user_id,
)
from services.track_record_insight import build_insight
from services.track_record_service import TrackRecordService

logger = logging.getLogger(__name__)

_WEEK_META_KEY = "signal_record_weekly_last_iso_week"
_SNAPSHOT_KEY_PREFIX = "signal_record_weekly_snapshot:"


def weekly_assessment_enabled() -> bool:
    return os.environ.get("SIGNAL_RECORD_WEEKLY_ASSESSMENT", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def current_iso_week() -> str:
    """UTC ISO week key, e.g. ``2026-W36``."""
    now = datetime.now(timezone.utc)
    iso = now.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _last_run_week() -> str | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT value FROM app_meta WHERE key = %s",
            (_WEEK_META_KEY,),
        ).fetchone()
    return str(row["value"]) if row else None


def _mark_week_complete(week_key: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO app_meta (key, value)
            VALUES (%s, %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """,
            (_WEEK_META_KEY, week_key),
        )
        conn.commit()


def _snapshot_key(user_id: int) -> str:
    return f"{_SNAPSHOT_KEY_PREFIX}{int(user_id)}"


def _store_snapshot(user_id: int, payload: dict[str, Any]) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO app_meta (key, value)
            VALUES (%s, %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """,
            (_snapshot_key(user_id), json.dumps(payload, separators=(",", ":"))),
        )
        conn.commit()


def load_latest_snapshot(user_id: int | None = None) -> dict[str, Any] | None:
    """Return the latest weekly snapshot for a user, or None."""
    uid = int(user_id if user_id is not None else get_current_user_id())
    with get_connection() as conn:
        row = conn.execute(
            "SELECT value FROM app_meta WHERE key = %s",
            (_snapshot_key(uid),),
        ).fetchone()
    if not row or not row["value"]:
        return None
    try:
        data = json.loads(str(row["value"]))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def should_run_this_week() -> bool:
    if not weekly_assessment_enabled():
        return False
    return _last_run_week() != current_iso_week()


def _compact_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """Persist a lean rollup — enough to re-read later without full bet rows."""
    overall = summary.get("overall") or {}
    by_kind = summary.get("byKind") or {}
    by_conf = summary.get("byConfidence") or []
    return {
        "overall": {
            "count": overall.get("count"),
            "wins": overall.get("wins"),
            "losses": overall.get("losses"),
            "neutrals": overall.get("neutrals"),
            "hitRate": overall.get("hitRate"),
            "avgReturn": overall.get("avgReturn"),
            "avgReturnAdj": overall.get("avgReturnAdj"),
            "calibratedHitRate": overall.get("calibratedHitRate"),
        },
        "byKind": {
            kind: {
                "count": bucket.get("count"),
                "hitRate": bucket.get("hitRate"),
                "calibratedHitRate": bucket.get("calibratedHitRate"),
                "avgReturnAdj": bucket.get("avgReturnAdj"),
            }
            for kind, bucket in by_kind.items()
            if isinstance(bucket, dict)
        },
        "byConfidence": [
            {
                "confidence": row.get("confidence"),
                "count": row.get("count"),
                "wins": row.get("wins"),
                "losses": row.get("losses"),
                "hitRate": row.get("hitRate"),
                "calibratedHitRate": row.get("calibratedHitRate"),
                "avgReturnAdj": row.get("avgReturnAdj"),
            }
            for row in by_conf
            if isinstance(row, dict)
        ],
        "pending": summary.get("pending"),
        "eraCutoffDate": summary.get("eraCutoffDate"),
        "excludedPreEra": summary.get("excludedPreEra"),
    }


def assess_user(user_id: int) -> dict[str, Any]:
    """Build and store one weekly self-assessment for ``user_id``."""
    token = set_current_user_id(user_id)
    try:
        summary = TrackRecordService().get_summary()
        insight = build_insight(summary)
        payload = {
            "week": current_iso_week(),
            "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "insight": insight,
            "summary": _compact_summary(summary),
        }
        _store_snapshot(user_id, payload)
        return {"userId": user_id, "week": payload["week"], "tone": insight.get("tone")}
    finally:
        reset_current_user_id(token)


def run_weekly_assessments(user_ids: list[int] | None = None) -> dict[str, Any]:
    """Run weekly Signal Record self-assessment for all (or given) users."""
    if not weekly_assessment_enabled():
        return {"skipped": True, "reason": "disabled"}

    week = current_iso_week()
    if _last_run_week() == week:
        return {"skipped": True, "reason": "already_ran", "week": week}

    ids = [int(u) for u in (user_ids if user_ids is not None else list_user_ids())]
    if not ids:
        _mark_week_complete(week)
        return {"skipped": True, "reason": "no_users", "week": week}

    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for user_id in ids:
        try:
            results.append(assess_user(user_id))
        except Exception as exc:  # noqa: BLE001 - continue other users
            logger.warning("Weekly signal self-assessment failed for user %s: %s", user_id, exc)
            errors.append({"userId": str(user_id), "error": str(exc)})

    _mark_week_complete(week)
    summary = {
        "week": week,
        "users": len(ids),
        "ok": len(results),
        "errors": errors,
    }
    logger.info(
        "Weekly signal self-assessment: %s ok, %s errors (UTC week %s).",
        len(results),
        len(errors),
        week,
    )
    return summary
