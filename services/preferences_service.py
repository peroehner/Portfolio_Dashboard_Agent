"""Per-user preferences — Portfolio Fit targets for the proposal framework.

Stored as JSONB on ``users.preferences_json``. Additive keys only.
See docs/PROPOSAL_FRAMEWORK.md (Slice 3).
"""

from __future__ import annotations

import json
from typing import Any

from db.database import get_connection, get_current_user_id

PORTFOLIO_FIT_KEYS = (
    "targetAnnualDividend",
    "volatilityPreference",
    "maxSingleNameWeightPct",
    "sectorCapPct",
    "taxLotPreference",
    "filterSetBias",
)

VOLATILITY_VALUES = frozenset({"low", "moderate", "high"})


def _empty_portfolio_fit() -> dict[str, Any]:
    return {key: None for key in PORTFOLIO_FIT_KEYS}


class PreferencesService:
    def get(self, user_id: int | None = None) -> dict[str, Any]:
        uid = user_id if user_id is not None else get_current_user_id()
        with get_connection() as conn:
            row = conn.execute(
                "SELECT preferences_json FROM users WHERE id = %s",
                (uid,),
            ).fetchone()
        raw = row["preferences_json"] if row else None
        data = self._parse(raw)
        fit = _empty_portfolio_fit()
        stored = data.get("portfolioFit") if isinstance(data.get("portfolioFit"), dict) else {}
        for key in PORTFOLIO_FIT_KEYS:
            if key in stored:
                fit[key] = stored[key]
        return {"portfolioFit": fit}

    def get_portfolio_fit(self, user_id: int | None = None) -> dict[str, Any]:
        return self.get(user_id=user_id)["portfolioFit"]

    def update(self, payload: dict[str, Any], user_id: int | None = None) -> dict[str, Any]:
        uid = user_id if user_id is not None else get_current_user_id()
        current = self.get(user_id=uid)
        fit = dict(current["portfolioFit"])
        incoming = payload.get("portfolioFit") if isinstance(payload.get("portfolioFit"), dict) else payload
        if not isinstance(incoming, dict):
            raise ValueError("preferences payload must be an object")

        if "targetAnnualDividend" in incoming:
            fit["targetAnnualDividend"] = self._parse_nonneg_number(
                incoming.get("targetAnnualDividend"), "targetAnnualDividend"
            )
        if "volatilityPreference" in incoming:
            fit["volatilityPreference"] = self._parse_volatility(
                incoming.get("volatilityPreference")
            )
        if "maxSingleNameWeightPct" in incoming:
            fit["maxSingleNameWeightPct"] = self._parse_pct(
                incoming.get("maxSingleNameWeightPct"), "maxSingleNameWeightPct"
            )
        for key in ("sectorCapPct", "taxLotPreference", "filterSetBias"):
            if key in incoming:
                fit[key] = incoming.get(key)

        blob = {"portfolioFit": fit}
        with get_connection() as conn:
            conn.execute(
                "UPDATE users SET preferences_json = %s::jsonb WHERE id = %s",
                (json.dumps(blob), uid),
            )
            conn.commit()
        return {"portfolioFit": fit}

    @staticmethod
    def _parse(raw: Any) -> dict[str, Any]:
        if raw is None:
            return {}
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
                return parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                return {}
        return {}

    @staticmethod
    def _parse_nonneg_number(value: Any, field: str) -> float | None:
        if value is None or value == "":
            return None
        try:
            num = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} must be a number") from exc
        if num < 0:
            raise ValueError(f"{field} must be ≥ 0")
        return round(num, 2)

    @staticmethod
    def _parse_volatility(value: Any) -> str | None:
        if value is None or value == "":
            return None
        text = str(value).strip().lower()
        if text not in VOLATILITY_VALUES:
            raise ValueError("volatilityPreference must be low, moderate, high, or null")
        return text

    @staticmethod
    def _parse_pct(value: Any, field: str) -> float | None:
        if value is None or value == "":
            return None
        try:
            num = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} must be a number") from exc
        if not 0 < num <= 100:
            raise ValueError(f"{field} must be between 0 and 100")
        return round(num, 2)
