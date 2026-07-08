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
    manual_ai_actions_per_day: int | None


PLAN_LIMITS: dict[str, PlanLimits] = {
    # Free keeps the prior 5 synth + 1 assess-all daily budget, but as one
    # clearer pool for all user-initiated AI actions.
    "free": PlanLimits(max_symbols=10, manual_ai_actions_per_day=6),
    "standard": PlanLimits(max_symbols=50, manual_ai_actions_per_day=None),
    "pro": PlanLimits(max_symbols=None, manual_ai_actions_per_day=None),
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
            SELECT note_syntheses, assess_all_runs, manual_ai_actions
            FROM user_daily_usage
            WHERE user_id = %s AND usage_date = %s
            """,
            (uid, today),
        ).fetchone()
    if not row:
        return {
            "date": today,
            "manualAiActions": 0,
            # Legacy fields kept for compatibility in UI/API consumers.
            "noteSyntheses": 0,
            "assessAllRuns": 0,
        }
    manual_ai_actions = int(
        row["manual_ai_actions"]
        if row.get("manual_ai_actions") is not None
        else int(row["note_syntheses"]) + int(row["assess_all_runs"])
    )
    return {
        "date": today,
        "manualAiActions": manual_ai_actions,
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
        "manualAiActionsPerDay": limits.manual_ai_actions_per_day,
        # Legacy fields kept for compatibility (same shared cap semantics now).
        "noteSynthesisPerDay": limits.manual_ai_actions_per_day,
        "assessAllPerDay": limits.manual_ai_actions_per_day,
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


def ensure_can_manual_ai_action(user_id: int | None = None) -> None:
    uid = user_id if user_id is not None else get_current_user_id()
    plan = get_user_plan(uid)
    limits = get_plan_limits(plan)
    if limits.manual_ai_actions_per_day is None:
        return
    used = get_daily_usage(uid)["manualAiActions"]
    if used >= limits.manual_ai_actions_per_day:
        raise PlanLimitExceeded(
            f"Daily Manual AI Actions limit reached ({limits.manual_ai_actions_per_day}/day on "
            f"{plan} plan). Upgrade for unlimited manual AI actions.",
            code="manual_ai_actions_limit",
            limit=limits.manual_ai_actions_per_day,
            used=used,
        )


def record_manual_ai_action(user_id: int | None = None) -> None:
    uid = user_id if user_id is not None else get_current_user_id()
    today = _utc_today()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO user_daily_usage (user_id, usage_date, manual_ai_actions)
            VALUES (%s, %s, 1)
            ON CONFLICT (user_id, usage_date)
            DO UPDATE SET manual_ai_actions = user_daily_usage.manual_ai_actions + 1
            """,
            (uid, today),
        )
        conn.commit()


def ensure_can_synthesize(user_id: int | None = None) -> None:
    ensure_can_manual_ai_action(user_id)


def record_note_synthesis(user_id: int | None = None) -> None:
    record_manual_ai_action(user_id)


def ensure_can_assess_all(user_id: int | None = None) -> None:
    ensure_can_manual_ai_action(user_id)


def record_assess_all(user_id: int | None = None) -> None:
    record_manual_ai_action(user_id)
