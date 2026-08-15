"""Per-user preferences — Portfolio Fit + Tax & Trim + Buy/Sell Plan controls.

Stored as JSONB on ``users.preferences_json``. Additive keys only; updates merge.
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
TAX_TRIM_PRICING = frozenset({"current", "threshold"})
TRADE_PLAN_QUAL = frozenset({"proximity", "score"})
TRADE_PLAN_LIST = frozenset({"sell", "buy"})


def _empty_portfolio_fit() -> dict[str, Any]:
    return {key: None for key in PORTFOLIO_FIT_KEYS}


def _default_tax_trim() -> dict[str, Any]:
    return {
        "pricingMode": "current",
        "lossScoreThreshold": 0,
        "trimScoreThreshold": 0,
        "matchLossPool": True,
    }


def _default_trade_plan() -> dict[str, Any]:
    return {
        "pricingMode": "current",
        "qualificationMode": "proximity",
        "sellProxThreshold": 10,
        "buyProxThreshold": 10,
        "sellScoreThreshold": 40,
        "buyScoreThreshold": 45,
        "sellBudget": 0,
        "buyBudget": 0,
        "listMode": "sell",
    }


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
        return {
            "portfolioFit": self._portfolio_fit_from(data),
            "taxTrim": self._tax_trim_from(data),
            "tradePlan": self._trade_plan_from(data),
        }

    def get_portfolio_fit(self, user_id: int | None = None) -> dict[str, Any]:
        return self.get(user_id=user_id)["portfolioFit"]

    def update(self, payload: dict[str, Any], user_id: int | None = None) -> dict[str, Any]:
        uid = user_id if user_id is not None else get_current_user_id()
        with get_connection() as conn:
            row = conn.execute(
                "SELECT preferences_json FROM users WHERE id = %s",
                (uid,),
            ).fetchone()
            data = self._parse(row["preferences_json"] if row else None)

            fit = self._portfolio_fit_from(data)
            tax_trim = self._tax_trim_from(data)
            trade_plan = self._trade_plan_from(data)

            if "portfolioFit" in payload or any(k in payload for k in PORTFOLIO_FIT_KEYS):
                incoming_fit = (
                    payload.get("portfolioFit")
                    if isinstance(payload.get("portfolioFit"), dict)
                    else payload
                )
                if not isinstance(incoming_fit, dict):
                    raise ValueError("preferences payload must be an object")
                fit = self._merge_portfolio_fit(fit, incoming_fit)

            if "taxTrim" in payload and payload.get("taxTrim") is not None:
                incoming_tax = payload.get("taxTrim")
                if not isinstance(incoming_tax, dict):
                    raise ValueError("taxTrim must be an object")
                tax_trim = self._merge_tax_trim(tax_trim or _default_tax_trim(), incoming_tax)

            if "tradePlan" in payload and payload.get("tradePlan") is not None:
                incoming_plan = payload.get("tradePlan")
                if not isinstance(incoming_plan, dict):
                    raise ValueError("tradePlan must be an object")
                trade_plan = self._merge_trade_plan(
                    trade_plan or _default_trade_plan(), incoming_plan
                )

            blob = {**data, "portfolioFit": fit}
            if tax_trim is not None:
                blob["taxTrim"] = tax_trim
            if trade_plan is not None:
                blob["tradePlan"] = trade_plan
            conn.execute(
                "UPDATE users SET preferences_json = %s::jsonb WHERE id = %s",
                (json.dumps(blob), uid),
            )
            conn.commit()
        return {"portfolioFit": fit, "taxTrim": tax_trim, "tradePlan": trade_plan}

    def _portfolio_fit_from(self, data: dict[str, Any]) -> dict[str, Any]:
        fit = _empty_portfolio_fit()
        stored = data.get("portfolioFit") if isinstance(data.get("portfolioFit"), dict) else {}
        for key in PORTFOLIO_FIT_KEYS:
            if key in stored:
                fit[key] = stored[key]
        return fit

    def _tax_trim_from(self, data: dict[str, Any]) -> dict[str, Any] | None:
        stored = data.get("taxTrim") if isinstance(data.get("taxTrim"), dict) else None
        if not stored:
            return None
        return self._merge_tax_trim(_default_tax_trim(), stored)

    def _trade_plan_from(self, data: dict[str, Any]) -> dict[str, Any] | None:
        stored = data.get("tradePlan") if isinstance(data.get("tradePlan"), dict) else None
        if not stored:
            return None
        return self._merge_trade_plan(_default_trade_plan(), stored)

    def _merge_portfolio_fit(self, fit: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
        out = dict(fit)
        if "targetAnnualDividend" in incoming:
            out["targetAnnualDividend"] = self._parse_nonneg_number(
                incoming.get("targetAnnualDividend"), "targetAnnualDividend"
            )
        if "volatilityPreference" in incoming:
            out["volatilityPreference"] = self._parse_volatility(
                incoming.get("volatilityPreference")
            )
        if "maxSingleNameWeightPct" in incoming:
            out["maxSingleNameWeightPct"] = self._parse_pct(
                incoming.get("maxSingleNameWeightPct"), "maxSingleNameWeightPct"
            )
        for key in ("sectorCapPct", "taxLotPreference", "filterSetBias"):
            if key in incoming:
                out[key] = incoming.get(key)
        return out

    def _merge_tax_trim(self, current: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
        out = dict(current)
        if "pricingMode" in incoming:
            mode = str(incoming.get("pricingMode") or "").strip().lower()
            if mode not in TAX_TRIM_PRICING:
                raise ValueError("taxTrim.pricingMode must be current or threshold")
            out["pricingMode"] = mode
        if "lossScoreThreshold" in incoming:
            out["lossScoreThreshold"] = self._parse_score_threshold(
                incoming.get("lossScoreThreshold"), "taxTrim.lossScoreThreshold"
            )
        if "trimScoreThreshold" in incoming:
            out["trimScoreThreshold"] = self._parse_score_threshold(
                incoming.get("trimScoreThreshold"), "taxTrim.trimScoreThreshold"
            )
        if "matchLossPool" in incoming:
            out["matchLossPool"] = bool(incoming.get("matchLossPool"))
        return out

    def _merge_trade_plan(self, current: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
        out = dict(current)
        if "pricingMode" in incoming:
            mode = str(incoming.get("pricingMode") or "").strip().lower()
            if mode not in TAX_TRIM_PRICING:
                raise ValueError("tradePlan.pricingMode must be current or threshold")
            out["pricingMode"] = mode
        if "qualificationMode" in incoming:
            mode = str(incoming.get("qualificationMode") or "").strip().lower()
            if mode not in TRADE_PLAN_QUAL:
                raise ValueError("tradePlan.qualificationMode must be proximity or score")
            out["qualificationMode"] = mode
        if "listMode" in incoming:
            mode = str(incoming.get("listMode") or "").strip().lower()
            if mode not in TRADE_PLAN_LIST:
                raise ValueError("tradePlan.listMode must be sell or buy")
            out["listMode"] = mode
        for field in (
            "sellProxThreshold",
            "buyProxThreshold",
            "sellScoreThreshold",
            "buyScoreThreshold",
            "sellBudget",
            "buyBudget",
        ):
            if field in incoming:
                out[field] = self._parse_score_threshold(incoming.get(field), f"tradePlan.{field}")
        return out

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

    @staticmethod
    def _parse_score_threshold(value: Any, field: str) -> float:
        if value is None or value == "":
            return 0.0
        try:
            num = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} must be a number") from exc
        if num < 0:
            raise ValueError(f"{field} must be ≥ 0")
        return round(num, 2)
