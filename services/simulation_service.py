from typing import Any

from psycopg.types.json import Json

from db.database import get_connection, get_current_user_id

# Aggregate-only snapshot of a planned-trade Simulation run. Persisted latest-per-user
# (overwrite) and surfaced on the Summary projection card. savedAt is set server-side.
_MONEY_FIELDS = (
    "projectedValuation",
    "projectedUpsidePct",
    "netCashFlow",
    "totalInvested",
    "totalGenerated",
    # Realized gains for the Summary metaline; tax is derived client-side from this
    # via SIM_TAX_RATE (matches the Simulation tab). Stored in the JSONB payload, so
    # no schema change is needed and older snapshots simply lack the key.
    "totalNetGains",
)
_COUNT_FIELDS = ("buyLegs", "sellLegs", "oversellCount", "scopeCount")
_FILTER_VALUES = frozenset({"all", "close", "far"})
_LEGS_VALUES = frozenset({"both", "buys", "sells"})
_PRICING_VALUES = frozenset({"threshold", "current"})


def _as_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_filter(value: Any) -> str:
    lowered = str(value or "all").strip().lower()
    return lowered if lowered in _FILTER_VALUES else "all"


def _as_legs(value: Any) -> str:
    lowered = str(value or "both").strip().lower()
    return lowered if lowered in _LEGS_VALUES else "both"


def _as_pricing(value: Any) -> str:
    lowered = str(value or "threshold").strip().lower()
    return lowered if lowered in _PRICING_VALUES else "threshold"


def _as_symbol_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    symbols: list[str] = []
    for item in value:
        if isinstance(item, str):
            symbol = item.strip().upper()
            if symbol:
                symbols.append(symbol)
    return symbols


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


class SimulationService:
    def get_snapshot(self) -> dict[str, Any] | None:
        user_id = get_current_user_id()
        with get_connection() as conn:
            row = conn.execute(
                "SELECT payload, saved_at FROM simulation_snapshots WHERE user_id = %s",
                (user_id,),
            ).fetchone()
        if not row:
            return None
        payload = dict(row["payload"] or {})
        payload["savedAt"] = row["saved_at"]
        return payload

    def save_snapshot(self, data: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {key: _as_float(data.get(key)) for key in _MONEY_FIELDS}
        for key in _COUNT_FIELDS:
            payload[key] = _as_int(data.get(key))

        payload["filter"] = _as_filter(data.get("filter"))
        payload["legs"] = _as_legs(data.get("legs"))
        payload["pricingMode"] = _as_pricing(data.get("pricingMode"))
        selected = _as_symbol_list(data.get("selectedSymbols"))
        use_selection = _as_bool(data.get("useSelection")) and bool(selected)
        payload["useSelection"] = use_selection
        payload["selectedSymbols"] = selected if use_selection else []

        user_id = get_current_user_id()
        with get_connection() as conn:
            row = conn.execute(
                """
                INSERT INTO simulation_snapshots (user_id, payload, saved_at)
                VALUES (%s, %s, app_now_text())
                ON CONFLICT (user_id) DO UPDATE SET
                    payload = excluded.payload,
                    saved_at = app_now_text()
                RETURNING saved_at
                """,
                (user_id, Json(payload)),
            ).fetchone()
            conn.commit()
        payload["savedAt"] = row["saved_at"]
        return payload
