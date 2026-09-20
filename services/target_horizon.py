"""Pers Target horizon as an explicit end date + linear progress laggard gate.

PT Horizon is bound to Pers Target as an end-of-thesis date (e.g. Q2-2027 or
2030), not a floating year count. Basis (start date + price) is captured when
the thesis is set so elapsed time and price progress stay anchored.

Laggard gate (alerts): fire when ≥50% of the window has elapsed AND actual
progress toward PT lags a linear path by ≥30 percentage points of the gap.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

LAGGARD_MIN_ELAPSED = 0.50
LAGGARD_MIN_LAG = 0.30  # fraction of PT gap behind linear expectation

_QUARTER_END = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}


def _as_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    # ISO date
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    return None


def parse_horizon_date(value: Any, *, today: date | None = None) -> date | None:
    """Normalize UI/API horizon input to an end date.

    Accepts:
      - empty → None
      - ISO date ``YYYY-MM-DD``
      - year ``YYYY`` → Dec 31 of that year
      - quarter ``Q2-2027`` / ``2027-Q2`` / ``Q2 2027`` → quarter end
    """
    if value is None or value == "":
        return None
    if isinstance(value, (date, datetime)):
        d = _as_date(value)
        return d

    text = str(value).strip()
    if not text:
        return None

    iso = _as_date(text)
    if iso is not None:
        return iso

    year_only = re.fullmatch(r"(20\d{2}|19\d{2})", text)
    if year_only:
        return date(int(year_only.group(1)), 12, 31)

    q = re.fullmatch(
        r"(?:Q\s*([1-4])[\s\-–/]*?(20\d{2}|19\d{2}))|(?:(20\d{2}|19\d{2})[\s\-–/]*?Q\s*([1-4]))",
        text,
        flags=re.IGNORECASE,
    )
    if q:
        if q.group(1) and q.group(2):
            quarter, year = int(q.group(1)), int(q.group(2))
        else:
            year, quarter = int(q.group(3)), int(q.group(4))
        month, day = _QUARTER_END[quarter]
        return date(year, month, day)

    return None


def format_horizon_date(value: Any) -> str | None:
    """Human display: ``Q2-2027``, ``2030``, or ``YYYY-MM-DD``."""
    d = _as_date(value)
    if d is None:
        return None
    for q, (month, day) in _QUARTER_END.items():
        if d.month == month and d.day == day:
            if q == 4 and month == 12 and day == 31:
                # Prefer bare year when thesis is end-of-year.
                return str(d.year)
            return f"Q{q}-{d.year}"
    if d.month == 12 and d.day == 31:
        return str(d.year)
    return d.isoformat()


def years_remaining(horizon_at: Any, *, today: date | None = None) -> float | None:
    """Years from today to horizon end (1 decimal); None if unset/past."""
    end = _as_date(horizon_at)
    if end is None:
        return None
    start = today or date.today()
    days = (end - start).days
    if days <= 0:
        return 0.0
    return round(days / 365.25, 1)


def years_span(basis_at: Any, horizon_at: Any) -> float | None:
    """Full thesis window length in years."""
    start = _as_date(basis_at)
    end = _as_date(horizon_at)
    if start is None or end is None:
        return None
    days = (end - start).days
    if days <= 0:
        return None
    return days / 365.25


def elapsed_fraction(
    basis_at: Any,
    horizon_at: Any,
    *,
    today: date | None = None,
) -> float | None:
    """0–1+ fraction of the thesis window that has elapsed."""
    start = _as_date(basis_at)
    end = _as_date(horizon_at)
    if start is None or end is None:
        return None
    total = (end - start).days
    if total <= 0:
        return None
    now = today or date.today()
    return (now - start).days / total


def price_progress_fraction(
    *,
    basis_price: Any,
    target_price: Any,
    current_price: Any,
) -> float | None:
    """Fraction of the PT gap closed since basis (can be negative if moved away)."""
    try:
        basis = float(basis_price)
        target = float(target_price)
        current = float(current_price)
    except (TypeError, ValueError):
        return None
    gap = target - basis
    if abs(gap) < 1e-9:
        return None
    return (current - basis) / gap


def progress_lag(
    *,
    basis_at: Any,
    horizon_at: Any,
    basis_price: Any,
    target_price: Any,
    current_price: Any,
    today: date | None = None,
) -> dict[str, Any] | None:
    """Compare actual PT progress to a linear path over the horizon window.

    Returns ``None`` when inputs are incomplete. ``lag`` is
    ``expected_progress − actual_progress`` (positive = behind schedule).
    """
    elapsed = elapsed_fraction(basis_at, horizon_at, today=today)
    actual = price_progress_fraction(
        basis_price=basis_price,
        target_price=target_price,
        current_price=current_price,
    )
    if elapsed is None or actual is None:
        return None
    expected = elapsed  # linear
    lag = expected - actual
    return {
        "elapsed": elapsed,
        "expected": expected,
        "actual": actual,
        "lag": lag,
        "isLaggard": elapsed >= LAGGARD_MIN_ELAPSED and lag >= LAGGARD_MIN_LAG,
    }


def is_progress_laggard(
    *,
    basis_at: Any,
    horizon_at: Any,
    basis_price: Any,
    target_price: Any,
    current_price: Any,
    today: date | None = None,
) -> bool:
    detail = progress_lag(
        basis_at=basis_at,
        horizon_at=horizon_at,
        basis_price=basis_price,
        target_price=target_price,
        current_price=current_price,
        today=today,
    )
    return bool(detail and detail["isLaggard"])


def average_years_remaining(rows: list[dict[str, Any]], *, today: date | None = None) -> float | None:
    """Average remaining years across rows with a set horizon (for TOTAL footers)."""
    vals: list[float] = []
    for row in rows:
        years = years_remaining(
            row.get("targetHorizonAt") or row.get("target_horizon_at"),
            today=today,
        )
        if years is not None and years > 0:
            vals.append(years)
    if not vals:
        return None
    return round(sum(vals) / len(vals), 1)
