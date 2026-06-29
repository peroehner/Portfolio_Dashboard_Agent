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
