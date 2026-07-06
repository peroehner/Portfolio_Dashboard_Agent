"""Subscription plan helpers (Phase B).

Plans are stored on ``users.plan``. Stripe webhooks will call ``set_user_plan``
later; until then, plans default to ``free`` and can be overridden locally via
``USER_PLAN_OVERRIDE`` for testing gates without billing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from db.database import get_connection, get_current_user_id

VALID_PLANS: tuple[str, ...] = ("free", "standard", "pro")
DEFAULT_PLAN = "free"


class PlanLimitExceeded(Exception):
    """Raised when a user hits a plan-gated limit."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        limit: int | None = None,
        used: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.limit = limit
        self.used = used


@dataclass(frozen=True)
class PlanLimits:
    max_symbols: int | None
    note_synthesis_per_day: int | None
    assess_all_per_day: int | None


PLAN_LIMITS: dict[str, PlanLimits] = {
    "free": PlanLimits(max_symbols=10, note_synthesis_per_day=5, assess_all_per_day=1),
    "standard": PlanLimits(max_symbols=50, note_synthesis_per_day=None, assess_all_per_day=None),
    "pro": PlanLimits(max_symbols=None, note_synthesis_per_day=None, assess_all_per_day=None),
}


def normalize_plan(value: str | None) -> str:
    plan = (value or DEFAULT_PLAN).strip().lower()
    if plan not in VALID_PLANS:
        allowed = ", ".join(VALID_PLANS)
        raise ValueError(f"Invalid plan {value!r}; expected one of: {allowed}")
    return plan


def plan_override() -> str | None:
    """Optional dev/staging override — never set in production."""
    override = os.environ.get("USER_PLAN_OVERRIDE", "").strip().lower()
    return override if override in VALID_PLANS else None


def get_user_plan(user_id: int | None = None) -> str:
    overridden = plan_override()
    if overridden is not None:
        return overridden
    uid = user_id if user_id is not None else get_current_user_id()
    with get_connection() as conn:
        row = conn.execute("SELECT plan FROM users WHERE id = %s", (uid,)).fetchone()
    if not row:
        return DEFAULT_PLAN
    return normalize_plan(row.get("plan"))


def set_user_plan(plan: str, user_id: int | None = None) -> str:
    """Persist a plan for a user (used by Stripe webhooks / admin tools)."""
    normalized = normalize_plan(plan)
    uid = user_id if user_id is not None else get_current_user_id()
    with get_connection() as conn:
        conn.execute("UPDATE users SET plan = %s WHERE id = %s", (normalized, uid))
        conn.commit()
    return normalized


def get_plan_limits(plan: str | None = None) -> PlanLimits:
    return PLAN_LIMITS[normalize_plan(plan or get_user_plan())]


def _utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def count_user_symbols(user_id: int | None = None) -> int:
    uid = user_id if user_id is not None else get_current_user_id()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM symbols WHERE user_id = %s",
            (uid,),
        ).fetchone()
    return int(row["c"])


def get_daily_usage(user_id: int | None = None) -> dict[str, Any]:
    uid = user_id if user_id is not None else get_current_user_id()
    today = _utc_today()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT note_syntheses, assess_all_runs
            FROM user_daily_usage
            WHERE user_id = %s AND usage_date = %s
            """,
            (uid, today),
        ).fetchone()
    if not row:
        return {"date": today, "noteSyntheses": 0, "assessAllRuns": 0}
    return {
        "date": today,
        "noteSyntheses": int(row["note_syntheses"]),
        "assessAllRuns": int(row["assess_all_runs"]),
    }


def limits_payload(plan: str | None = None, user_id: int | None = None) -> dict[str, Any]:
    resolved_plan = plan or get_user_plan(user_id)
    limits = get_plan_limits(resolved_plan)
    usage = get_daily_usage(user_id)
    return {
        "plan": resolved_plan,
        "maxSymbols": limits.max_symbols,
        "symbolCount": count_user_symbols(user_id),
        "noteSynthesisPerDay": limits.note_synthesis_per_day,
        "assessAllPerDay": limits.assess_all_per_day,
        "usage": usage,
    }


def ensure_can_add_symbols(additional: int = 1, user_id: int | None = None) -> None:
    if additional <= 0:
        return
    uid = user_id if user_id is not None else get_current_user_id()
    plan = get_user_plan(uid)
    limits = get_plan_limits(plan)
    if limits.max_symbols is None:
        return
    current = count_user_symbols(uid)
    if current + additional > limits.max_symbols:
        raise PlanLimitExceeded(
            f"Symbol limit reached ({limits.max_symbols} on {plan} plan). "
            "Upgrade to add more symbols.",
            code="symbol_limit",
            limit=limits.max_symbols,
            used=current,
        )


def ensure_can_synthesize(user_id: int | None = None) -> None:
    uid = user_id if user_id is not None else get_current_user_id()
    plan = get_user_plan(uid)
    limits = get_plan_limits(plan)
    if limits.note_synthesis_per_day is None:
        return
    used = get_daily_usage(uid)["noteSyntheses"]
    if used >= limits.note_synthesis_per_day:
        raise PlanLimitExceeded(
            f"Daily note synthesis limit reached ({limits.note_synthesis_per_day}/day on "
            f"{plan} plan). Upgrade for unlimited synthesis.",
            code="note_synthesis_limit",
            limit=limits.note_synthesis_per_day,
            used=used,
        )


def record_note_synthesis(user_id: int | None = None) -> None:
    uid = user_id if user_id is not None else get_current_user_id()
    today = _utc_today()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO user_daily_usage (user_id, usage_date, note_syntheses)
            VALUES (%s, %s, 1)
            ON CONFLICT (user_id, usage_date)
            DO UPDATE SET note_syntheses = user_daily_usage.note_syntheses + 1
            """,
            (uid, today),
        )
        conn.commit()


def ensure_can_assess_all(user_id: int | None = None) -> None:
    uid = user_id if user_id is not None else get_current_user_id()
    plan = get_user_plan(uid)
    limits = get_plan_limits(plan)
    if limits.assess_all_per_day is None:
        return
    used = get_daily_usage(uid)["assessAllRuns"]
    if used >= limits.assess_all_per_day:
        raise PlanLimitExceeded(
            f"Daily Assess All limit reached ({limits.assess_all_per_day}/day on "
            f"{plan} plan). Upgrade for unlimited portfolio assessments.",
            code="assess_all_limit",
            limit=limits.assess_all_per_day,
            used=used,
        )


def record_assess_all(user_id: int | None = None) -> None:
    uid = user_id if user_id is not None else get_current_user_id()
    today = _utc_today()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO user_daily_usage (user_id, usage_date, assess_all_runs)
            VALUES (%s, %s, 1)
            ON CONFLICT (user_id, usage_date)
            DO UPDATE SET assess_all_runs = user_daily_usage.assess_all_runs + 1
            """,
            (uid, today),
        )
        conn.commit()
