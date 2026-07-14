import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Blueprint, jsonify, request

from api.openapi_spec import OPENAPI_SPEC
from db.database import get_connection, get_current_user_id, get_user
from services.alerts_service import AlertsService
from services.assessment_service import AssessmentService
from services.fib_service import FibService
from services.fundamentals_service import FundamentalsService
from services.holdings_service import HoldingsService
from services.import_service import ImportService
from services.inspector_service import InspectorService
from services.notes_service import NotesService
from services import news_relevance_service
from services.overview_service import OverviewService
from services.portfolio_service import PortfolioService
from services.screening_service import ScreeningService
from services.simulation_service import SimulationService
from services.technical_service import TechnicalService
from services.track_record_service import TrackRecordService
from services.llm_client import LLMClient
from services.plan_service import normalize_plan, plan_override

v1_bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")

SAMPLE_PORTFOLIO_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "Sample-Portfolio.json"
)


def _plan_limit_response(exc) -> tuple:
    from services.plan_service import PlanLimitExceeded

    assert isinstance(exc, PlanLimitExceeded)
    body: dict = {"error": str(exc), "code": exc.code}
    if exc.limit is not None:
        body["limit"] = exc.limit
    if exc.used is not None:
        body["used"] = exc.used
    return jsonify(body), 403


def _app_build_id() -> str | None:
    """Short git/deploy id for the About panel (env on Render, else local git)."""
    for key in ("BUILD_SHA", "RENDER_GIT_COMMIT", "GIT_COMMIT"):
        val = (os.environ.get(key) or "").strip()
        if val:
            return val[:12]
    try:
        import subprocess
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return out or None
    except Exception:
        return None


def _author_email() -> str:
    configured = (os.environ.get("AUTHOR_EMAIL") or "").strip().lower()
    if configured:
        return configured
    return (os.environ.get("BOOTSTRAP_USER_EMAIL") or "local@portfolio.local").strip().lower()


def _author_console_allowed() -> bool:
    try:
        user = get_user(get_current_user_id())
    except Exception:
        return False
    if not user:
        return False
    email = str(user.get("email") or "").strip().lower()
    return bool(email) and email == _author_email()

portfolio_service = PortfolioService()
notes_service = NotesService()
alerts_service = AlertsService()
fib_service = FibService()
assessment_service = AssessmentService()
holdings_service = HoldingsService()
import_service = ImportService()
overview_service = OverviewService()
screening_service = ScreeningService()
simulation_service = SimulationService()
inspector_service = InspectorService()
fundamentals_service = FundamentalsService()
technical_service = TechnicalService()
track_record_service = TrackRecordService()


def _engine():
    from main import get_engine
    return get_engine()


@v1_bp.route("/health", methods=["GET"])
def health():
    client = LLMClient()
    return jsonify({
        "status": "ok",
        "version": "v1",
        "assessmentProvider": client.active_provider(),
    })


@v1_bp.route("/me", methods=["GET"])
def get_me():
    """Current authenticated user (or the bootstrap user when auth is disabled)."""
    from auth import AUTH_ENABLED
    from db.database import get_current_user_id, get_user
    from services.plan_service import get_user_plan, limits_payload

    user_id = get_current_user_id()
    user = get_user(user_id)
    plan = get_user_plan(user_id) if user else None
    return jsonify({
        "authEnabled": AUTH_ENABLED,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "name": user["name"],
            "picture": user["picture"],
            "plan": plan,
        } if user else None,
        "planLimits": limits_payload(plan, user_id) if user else None,
    })


@v1_bp.route("/preferences", methods=["PATCH"])
def update_preferences():
    """Reserved for future per-user preferences."""
    return jsonify({})

@v1_bp.route("/config", methods=["GET"])
def get_config():
    client = LLMClient()
    provider = client.active_provider()
    return jsonify({
        "version": "v1",
        "appVersion": "1.0",
        "build": _app_build_id(),
        "assessmentProvider": provider,
        "assessmentMode": client.mode,
        "llmConfigured": provider != "rules",
        "syncIntervalSeconds": 300,
        "fibProximityPct": float(os.environ.get("FIB_PROXIMITY_PCT", "1.0")),
        "importVersion": 8,
        "importModes": ["merge", "replace"],
        "features": {
            "noteSynthesis": True,
            "authorConsoleEnabled": _author_console_allowed(),
        },
        "geminiModel": client.gemini_model if client.active_provider() == "gemini" else None,
        "docs": {
            "api": "/docs/api",
            "replit": "/docs/replit",
            "openapi": "/api/v1/openapi.json",
        },
    })


@v1_bp.route("/consol", methods=["GET"])
def consol_workload():
    """Author-only workload snapshot for hidden console tab."""
    if not _author_console_allowed():
        return jsonify({"error": "Not found"}), 404

    with get_connection() as conn:
        totals_row = conn.execute(
            """
            SELECT
                COUNT(DISTINCT symbol) AS synced_symbols,
                COUNT(DISTINCT user_id) AS users_with_symbols,
                COUNT(*) AS symbol_rows
            FROM symbols
            """
        ).fetchone()
        user_rows = conn.execute(
            """
            SELECT
                u.id,
                u.email,
                u.plan,
                COUNT(s.symbol) AS symbol_count
            FROM users u
            LEFT JOIN symbols s ON s.user_id = u.id
            GROUP BY u.id, u.email, u.plan
            ORDER BY symbol_count DESC, u.id
            """
        ).fetchall()
        assessed_row = conn.execute(
            """
            SELECT COUNT(*) AS assessed_today
            FROM symbol_assessment
            WHERE as_of_date = to_char(timezone('UTC', now()), 'YYYY-MM-DD')
            """
        ).fetchone()
        utc_row = conn.execute(
            "SELECT to_char(timezone('UTC', now()), 'YYYY-MM-DD') AS utc_date"
        ).fetchone()
        usage_rows = conn.execute(
            """
            SELECT
                udu.user_id,
                u.email,
                u.plan,
                udu.manual_ai_actions,
                udu.assess_all_runs
            FROM user_daily_usage udu
            JOIN users u ON u.id = udu.user_id
            WHERE udu.usage_date = to_char(timezone('UTC', now()), 'YYYY-MM-DD')
            ORDER BY udu.manual_ai_actions DESC, udu.assess_all_runs DESC, udu.user_id
            """
        ).fetchall()
        trend_rows = conn.execute(
            """
            SELECT as_of_date, COUNT(*) AS assessed_count
            FROM symbol_assessment
            WHERE as_of_date >= to_char(timezone('UTC', now()) - interval '6 days', 'YYYY-MM-DD')
            GROUP BY as_of_date
            ORDER BY as_of_date
            """
        ).fetchall()

    today_utc = datetime.now(timezone.utc).date()
    trend_by_date = {
        str(row["as_of_date"]): int(row["assessed_count"] or 0) for row in trend_rows
    }
    assessed_last_7_days = []
    for offset in range(6, -1, -1):
        day = today_utc - timedelta(days=offset)
        iso = day.isoformat()
        assessed_last_7_days.append({"date": iso, "assessed": trend_by_date.get(iso, 0)})

    override = plan_override()
    from services.consol_service import build_footprint_snapshot

    return jsonify(
        {
            "authorEmail": _author_email(),
            "utcDate": utc_row["utc_date"],
            "planOverride": override,
            "syncIntervalSeconds": 300,
            "footprint": build_footprint_snapshot(),
            "totals": {
                "syncedSymbols": int(totals_row["synced_symbols"] or 0),
                "usersWithSymbols": int(totals_row["users_with_symbols"] or 0),
                "symbolRows": int(totals_row["symbol_rows"] or 0),
                "assessedToday": int(assessed_row["assessed_today"] or 0),
            },
            "assessedLast7Days": assessed_last_7_days,
            "users": [
                {
                    "id": int(row["id"]),
                    "email": row["email"],
                    "tier": normalize_plan(row.get("plan")),
                    "symbolCount": int(row["symbol_count"] or 0),
                }
                for row in user_rows
            ],
            "usageToday": [
                {
                    "userId": int(row["user_id"]),
                    "email": row["email"],
                    "tier": normalize_plan(row.get("plan")),
                    "manualAiActions": int(row["manual_ai_actions"] or 0),
                    "assessAllRuns": int(row["assess_all_runs"] or 0),
                }
                for row in usage_rows
            ],
        }
    )


@v1_bp.route("/openapi.json", methods=["GET"])
def openapi_spec():
    return jsonify(OPENAPI_SPEC)


@v1_bp.route("/symbols", methods=["GET"])
def list_symbols():
    return jsonify({"symbols": portfolio_service.list_symbols()})


@v1_bp.route("/patterns", methods=["GET"])
def list_patterns():
    """Top detected chart pattern per portfolio symbol, for badging the list.

    Patterns are derived from (cached) price history and are user-independent, so
    they can be computed in parallel without per-thread user context."""
    from services.assessment_service import ASSESSMENT_TECHNICALS
    from services.market_cache import yf_pool
    from services.technical_signals_service import TechnicalSignalsService

    if not ASSESSMENT_TECHNICALS:
        return jsonify({"patterns": {}})

    symbols = [s["symbol"] for s in portfolio_service.list_symbols()]
    if not symbols:
        return jsonify({"patterns": {}})

    svc = TechnicalSignalsService()

    def top_pattern(symbol):
        signals = svc.get_signals(symbol)
        patterns = (signals or {}).get("patterns") or []
        if not patterns:
            return symbol, None
        p = patterns[0]
        return symbol, {
            "name": p.get("name"),
            "type": p.get("type"),
            "status": p.get("status"),
            "confidence": p.get("confidence"),
            "verdict": (p.get("validation") or {}).get("verdict"),
        }

    out: dict[str, dict] = {}
    for symbol, pattern in yf_pool.map(top_pattern, symbols):
        if pattern:
            out[symbol] = pattern
    return jsonify({"patterns": out})


@v1_bp.route("/symbols/<symbol>", methods=["GET"])
def get_symbol(symbol):
    item = portfolio_service.get_symbol(symbol)
    if item is None:
        return jsonify({"error": f"Symbol {symbol.upper()} not found."}), 404
    return jsonify(item)


@v1_bp.route("/symbols", methods=["POST"])
def create_symbol():
    data = request.get_json(silent=True) or {}
    symbol = data.get("symbol")
    if not symbol:
        return jsonify({"error": "symbol is required."}), 400
    try:
        item = portfolio_service.upsert_symbol(symbol, data)
    except Exception as exc:
        from services.plan_service import PlanLimitExceeded

        if isinstance(exc, PlanLimitExceeded):
            return _plan_limit_response(exc)
        raise
    # Pull a live quote for just this new symbol so the Target detail panel can
    # show its current price immediately (best-effort; a bad ticker just leaves
    # the price empty and the symbol still gets created for editing).
    try:
        portfolio_service.sync_prices(_engine(), symbols=[item["symbol"]])
        item = portfolio_service.get_symbol(item["symbol"]) or item
    except Exception as exc:  # noqa: BLE001 - price fetch is non-fatal
        logging.getLogger(__name__).warning(
            "Price fetch for new symbol %s failed: %s", item.get("symbol"), exc
        )
    return jsonify(item), 201


@v1_bp.route("/symbols/<symbol>", methods=["PUT"])
def update_symbol(symbol):
    data = request.get_json(silent=True) or {}
    if portfolio_service.get_symbol(symbol) is None:
        return jsonify({"error": f"Symbol {symbol.upper()} not found."}), 404
    item = portfolio_service.upsert_symbol(symbol, data)
    return jsonify(item)


@v1_bp.route("/symbols/<symbol>", methods=["DELETE"])
def delete_symbol(symbol):
    if not portfolio_service.delete_symbol(symbol):
        return jsonify({"error": f"Symbol {symbol.upper()} not found."}), 404
    return jsonify({"status": "deleted", "symbol": symbol.upper()})


@v1_bp.route("/symbols/<symbol>/notes", methods=["GET"])
def list_notes(symbol):
    if portfolio_service.get_symbol(symbol) is None:
        return jsonify({"error": f"Symbol {symbol.upper()} not found."}), 404
    return jsonify({"symbol": symbol.upper(), "notes": notes_service.list_notes(symbol)})


@v1_bp.route("/symbols/<symbol>/notes", methods=["POST"])
def add_note(symbol):
    data = request.get_json(silent=True) or {}
    try:
        note = notes_service.add_note(symbol, data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(note), 201


@v1_bp.route("/symbols/<symbol>/notes/synthesize", methods=["POST", "OPTIONS"])
def synthesize_all_notes(symbol):
    if request.method == "OPTIONS":
        return "", 204
    if portfolio_service.get_symbol(symbol) is None:
        return jsonify({"error": f"Symbol {symbol.upper()} not found."}), 404
    force = request.args.get("force", "").lower() in ("1", "true", "yes")
    data = request.get_json(silent=True) or {}
    guidance = data.get("guidance")
    try:
        notes = notes_service.synthesize_all_notes(symbol, force=force, guidance=guidance)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 502
    except Exception as exc:
        from services.plan_service import PlanLimitExceeded

        if isinstance(exc, PlanLimitExceeded):
            return _plan_limit_response(exc)
        raise
    return jsonify({"symbol": symbol.upper(), "notes": notes})


@v1_bp.route("/symbols/<symbol>/notes/<int:note_id>/synthesize", methods=["POST", "OPTIONS"])
def synthesize_note(symbol, note_id):
    if request.method == "OPTIONS":
        return "", 204
    if portfolio_service.get_symbol(symbol) is None:
        return jsonify({"error": f"Symbol {symbol.upper()} not found."}), 404
    force = request.args.get("force", "").lower() in ("1", "true", "yes")
    data = request.get_json(silent=True) or {}
    guidance = data.get("guidance")
    try:
        note = notes_service.synthesize_note(symbol, note_id, force=force, guidance=guidance)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 502
    except Exception as exc:
        from services.plan_service import PlanLimitExceeded

        if isinstance(exc, PlanLimitExceeded):
            return _plan_limit_response(exc)
        raise
    return jsonify(note)


@v1_bp.route("/symbols/<symbol>/notes/<int:note_id>", methods=["PUT", "PATCH"])
def update_note(symbol, note_id):
    data = request.get_json(silent=True) or {}
    try:
        note = notes_service.update_note(symbol, note_id, data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404 if "not found" in str(exc).lower() else 400
    return jsonify(note)


@v1_bp.route("/symbols/<symbol>/notes/<int:note_id>", methods=["DELETE"])
def delete_note(symbol, note_id):
    if not notes_service.delete_note(symbol, note_id):
        return jsonify({"error": "Note not found."}), 404
    return jsonify({"status": "deleted", "id": note_id})


@v1_bp.route("/portfolio", methods=["GET"])
def get_portfolio():
    symbols = [portfolio_service.get_symbol(item["symbol"]) for item in portfolio_service.list_symbols()]
    return jsonify({"symbols": symbols})


@v1_bp.route("/overview", methods=["GET"])
def get_overview():
    return jsonify(overview_service.get_overview())


@v1_bp.route("/simulation/snapshot", methods=["GET"])
def get_simulation_snapshot():
    return jsonify({"simulation": simulation_service.get_snapshot()})


@v1_bp.route("/simulation/snapshot", methods=["POST"])
def save_simulation_snapshot():
    data = request.get_json(silent=True) or {}
    return jsonify({"simulation": simulation_service.save_snapshot(data)})


@v1_bp.route("/sample-portfolio", methods=["GET"])
def get_sample_portfolio():
    """Read-only starter portfolio for empty-state onboarding (merge-importable)."""
    if not SAMPLE_PORTFOLIO_PATH.is_file():
        return jsonify({"error": "Sample portfolio not found."}), 404
    return jsonify(json.loads(SAMPLE_PORTFOLIO_PATH.read_text(encoding="utf-8")))


@v1_bp.route("/import", methods=["POST"])
def import_payload():
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"error": "JSON body required."}), 400
    mode = request.args.get("mode") or (payload.get("mode") if isinstance(payload, dict) else None) or "merge"
    if isinstance(payload, dict):
        payload = {k: v for k, v in payload.items() if k != "mode"}
    try:
        result = import_service.import_payload(payload, mode=mode)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        from services.plan_service import PlanLimitExceeded

        if isinstance(exc, PlanLimitExceeded):
            return _plan_limit_response(exc)
        raise
    return jsonify({"status": "success", **result})


@v1_bp.route("/import/file", methods=["POST"])
def import_file():
    if "file" not in request.files:
        return jsonify({"error": "Upload a JSON, CSV, or TXT analysis file as 'file'."}), 400
    upload = request.files["file"]
    mode = request.form.get("mode") or request.args.get("mode") or "merge"
    try:
        result = import_service.import_file(
            upload.filename or "upload.txt",
            upload.read(),
            content_type=upload.mimetype,
            mode=mode,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        from services.plan_service import PlanLimitExceeded

        if isinstance(exc, PlanLimitExceeded):
            return _plan_limit_response(exc)
        raise
    logging.info(
        "Import file %s mode=%s cleared=%s imported=%s portfolio=%s",
        upload.filename,
        result.get("mode"),
        result.get("clearedSymbols"),
        result.get("symbolsImported"),
        len(result.get("symbols") or []),
    )
    return jsonify({"status": "success", **result})


@v1_bp.route("/export", methods=["GET"])
def export_portfolio():
    """Export the full portfolio as a tolerant, human-editable JSON document.

    Each position carries the minimal set (symbol, shares, purchaseDate, avgCost)
    plus thresholds, personal/analyst targets, dividend, and personal notes when
    they exist. Re-importing this file (replace mode) restores the DB state.
    """
    from datetime import datetime, timezone

    include_notes = request.args.get("notes", default="1") != "0"
    symbols = portfolio_service.list_symbols()
    holdings = {h["symbol"]: h for h in holdings_service.list_holdings()}

    def prune(d):
        return {k: v for k, v in d.items() if v not in (None, "", [])}

    positions = []
    for sym in symbols:
        ticker = sym["symbol"]
        h = holdings.get(ticker, {})
        notes_out = []
        if include_notes:
            for n in notes_service.list_notes(ticker):
                notes_out.append(prune({
                    "date": n.get("date"),
                    "source": n.get("source"),
                    "text": n.get("text"),
                    "synthesis": n.get("synthesis"),
                    "synthesisProvider": n.get("synthesisProvider"),
                    "synthesizedAt": n.get("synthesizedAt"),
                }))
        position = {
            # Minimal core (always present, even if null, for easy editing)
            "symbol": ticker,
            "shares": h.get("quantity"),
            "purchaseDate": h.get("purchaseDate"),
            "avgCost": h.get("costBasis"),
        }
        # Optional extras, only when set
        position.update(prune({
            "account": h.get("accountName"),
            "currentPrice": sym.get("currentPrice"),
            "targetPrice": sym.get("targetPrice"),
            "analystTarget1y": sym.get("analystTarget1y"),
            "buyBelow": sym.get("buyBelow"),
            "sellAbove": sym.get("sellAbove"),
            # Planned-trade thresholds + signed share amounts (sign = direction).
            "tradeBelowPrice": sym.get("tradeBelowPrice"),
            "tradeBelowShares": sym.get("tradeBelowShares"),
            "tradeAbovePrice": sym.get("tradeAbovePrice"),
            "tradeAboveShares": sym.get("tradeAboveShares"),
            "annualDividend": sym.get("annualDividend"),
        }))
        if notes_out:
            position["notes"] = notes_out
        # Technical-analysis snapshot (trend waves + Fibonacci levels) from the
        # legacy TA-Analyst import — included so a replace-import restores it.
        tech = technical_service.get_snapshot(ticker)
        if tech:
            technical_out = prune({
                "windowStart": tech.get("windowStart"),
                "windowEnd": tech.get("windowEnd"),
                "fibAnchor": tech.get("fibAnchor"),
                "trends": tech.get("trends"),
                "fibLevels": tech.get("fibLevels"),
            })
            if technical_out.get("trends") or technical_out.get("fibLevels"):
                position["technical"] = technical_out
        positions.append(position)

    document = {
        "format": "portfolio-dashboard",
        "version": 1,
        "exportedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "currency": "USD",
        "positions": positions,
    }

    response = jsonify(document)
    if request.args.get("download"):
        stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
        filename = f"DA-{len(positions)}-{stamp}.json"
        response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@v1_bp.route("/holdings", methods=["GET"])
def list_holdings():
    return jsonify({"holdings": holdings_service.list_holdings()})


@v1_bp.route("/holdings", methods=["POST"])
def create_holding():
    data = request.get_json(silent=True) or {}
    symbol = data.get("symbol")
    if not symbol:
        return jsonify({"error": "symbol is required."}), 400
    holding = holdings_service.upsert_holding(symbol, data)
    if holding is None:
        return jsonify({"status": "deleted", "symbol": symbol.upper()})
    return jsonify(holding), 201


@v1_bp.route("/holdings/<symbol>", methods=["PUT"])
def update_holding(symbol):
    data = request.get_json(silent=True) or {}
    holding = holdings_service.upsert_holding(symbol, data)
    if holding is None:
        return jsonify({"status": "deleted", "symbol": symbol.upper()})
    return jsonify(holding)


@v1_bp.route("/holdings/<symbol>", methods=["DELETE"])
def delete_holding(symbol):
    if not holdings_service.delete_holding(symbol):
        return jsonify({"error": f"Holding for {symbol.upper()} not found."}), 404
    return jsonify({"status": "deleted", "symbol": symbol.upper()})


@v1_bp.route("/screen", methods=["GET"])
def run_screen():
    filters = {
        "minUpside": request.args.get("minUpside", type=float),
        "belowBuy": request.args.get("belowBuy", "").lower() in ("1", "true", "yes"),
        "nearFib": request.args.get("nearFib", "").lower() in ("1", "true", "yes"),
        "hasAlerts": request.args.get("hasAlerts", "").lower() in ("1", "true", "yes"),
        "sort": request.args.get("sort", "score"),
        "order": request.args.get("order", "desc"),
    }
    return jsonify({"results": screening_service.run_screen(filters)})


@v1_bp.route("/fib-proximity", methods=["GET"])
def fib_proximity():
    raw = request.args.get("symbols", "").strip()
    if raw:
        symbols = [part.strip().upper() for part in raw.split(",") if part.strip()]
        return jsonify({"results": screening_service.fib_proximity_map(symbols=symbols)})
    return jsonify({"results": screening_service.fib_proximity_map()})


@v1_bp.route("/symbols/<symbol>/inspector", methods=["GET"])
def inspect_symbol(symbol):
    # The market-grounded news sentiment is the only relatively expensive part of
    # the inspector (a per-symbol price-reaction event study). The frontend passes
    # includeNews=false and fetches it lazily + memoizes per symbol for the session
    # so switching back and forth doesn't re-run it every time.
    include_news = request.args.get("includeNews", "true").strip().lower() not in (
        "0",
        "false",
        "no",
    )
    lite = request.args.get("lite", "0").strip().lower() in ("1", "true", "yes")
    result = inspector_service.inspect(symbol, include_news=include_news, lite=lite)
    if result is None:
        return jsonify({"error": f"Symbol {symbol.upper()} not found."}), 404
    return jsonify(result)


@v1_bp.route("/symbols/<symbol>/news-sentiment", methods=["GET"])
def get_news_sentiment(symbol):
    """Lazy, standalone market-grounded news sentiment for one symbol.

    This is the same Phase 1 daily event-study sentiment that ``inspect`` embeds
    in the recommendation, exposed on its own so the inspector can fetch it only
    when a symbol's news is actually displayed and cache it client-side. Returns
    ``newsSentiment: null`` when there is no materially-relevant news."""
    if portfolio_service.get_symbol(symbol) is None:
        return jsonify({"error": f"Symbol {symbol.upper()} not found."}), 404
    sentiment = inspector_service._news_sentiment_for_symbol(symbol)
    return jsonify({"symbol": symbol.upper(), "newsSentiment": sentiment})


@v1_bp.route("/alerts", methods=["GET"])
def list_alerts():
    symbol = request.args.get("symbol")
    status = request.args.get("status", "active")
    alerts = alerts_service.list_alerts(symbol=symbol, status=status)
    return jsonify({"alerts": alerts})


@v1_bp.route("/alerts/evaluate", methods=["POST"])
def evaluate_alerts():
    if not portfolio_service.list_symbols():
        return jsonify({"error": "No symbols in portfolio."}), 400
    portfolio_service.sync_prices(_engine())
    new_alerts = alerts_service.evaluate_all(_engine())
    active_alerts = alerts_service.list_alerts()
    return jsonify({"status": "success", "newAlerts": new_alerts, "alerts": active_alerts})


@v1_bp.route("/alerts/<int:alert_id>/dismiss", methods=["POST"])
def dismiss_alert(alert_id):
    if not alerts_service.dismiss_alert(alert_id):
        return jsonify({"error": "Alert not found or already dismissed."}), 404
    return jsonify({"status": "dismissed", "id": alert_id})


@v1_bp.route("/assessments", methods=["GET"])
def list_assessments():
    symbol = request.args.get("symbol")
    limit = int(request.args.get("limit", 20))
    return jsonify({"assessments": assessment_service.list_assessments(symbol=symbol, limit=limit)})


@v1_bp.route("/assessments/<int:assessment_id>", methods=["DELETE"])
def delete_assessment(assessment_id):
    symbol = request.args.get("symbol")
    if not assessment_service.delete_assessment(assessment_id, symbol=symbol):
        return jsonify({"error": "Assessment not found."}), 404
    return jsonify({"status": "deleted", "id": assessment_id})


@v1_bp.route("/assess", methods=["POST"])
def assess_portfolio():
    data = request.get_json(silent=True) or {}
    symbols = data.get("symbols")
    if not portfolio_service.list_symbols():
        return jsonify({"error": "No symbols in portfolio."}), 400
    try:
        assessments = assessment_service.assess_portfolio(symbols=symbols)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 502
    except Exception as exc:
        from services.plan_service import PlanLimitExceeded

        if isinstance(exc, PlanLimitExceeded):
            return _plan_limit_response(exc)
        raise
    return jsonify({"status": "success", "assessments": assessments})


@v1_bp.route("/symbols/<symbol>/assess", methods=["POST"])
def assess_symbol(symbol):
    if portfolio_service.get_symbol(symbol) is None:
        return jsonify({"error": f"Symbol {symbol.upper()} not found."}), 404
    try:
        assessment = assessment_service.assess_symbol(symbol)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 502
    return jsonify(assessment), 201


@v1_bp.route("/fundamentals", methods=["GET"])
def list_fundamentals():
    include_news = request.args.get("includeNews", default=1, type=int) > 0
    symbols_meta = portfolio_service.list_symbols()
    enrichment = fundamentals_service.get_enrichment_bulk([s["symbol"] for s in symbols_meta])
    rows = []
    for meta in symbols_meta:
        symbol = meta["symbol"]
        data = enrichment.get(symbol.upper(), {})
        row = {
            "symbol": symbol,
            "currentPrice": meta.get("currentPrice"),
            "dayChangePct": meta.get("dayChangePct"),
            "fundamentals": data.get("fundamentals", {}),
        }
        if include_news:
            row["recentNews"] = data.get("recentNews", [])
        rows.append(row)
    return jsonify({"symbols": rows})


@v1_bp.route("/recommendation-changes", methods=["GET"])
def recommendation_changes():
    """DB-backed SAI action changelog (lightweight; no market enrichment)."""
    limit = request.args.get("limit", default=0, type=int)
    if limit <= 0:
        changes = assessment_service.list_recommendation_changes(limit=None)
    else:
        changes = assessment_service.list_recommendation_changes(limit=limit)
    return jsonify({"changes": changes, "total": len(changes)})


@v1_bp.route("/news-feed", methods=["GET"])
def news_feed():
    """Compact Summary feed: latest recommendation changes + top recent news."""
    # Default 0 == return the full ranked list (the feed is scrollable). A
    # positive newsLimit still caps the response for any callers that want it.
    news_limit = request.args.get("newsLimit", default=0, type=int)
    skip_changes = request.args.get("skipChanges", default=0, type=int) > 0
    changes_limit = request.args.get("changesLimit", default=0, type=int)

    if skip_changes:
        changes = []
        changes_total = assessment_service.count_recommendation_changes()
    elif changes_limit <= 0:
        changes = assessment_service.list_recommendation_changes(limit=None)
        changes_total = len(changes)
    else:
        changes = assessment_service.list_recommendation_changes(limit=changes_limit)
        changes_total = assessment_service.count_recommendation_changes()

    symbols_meta = portfolio_service.list_symbols()
    enrichment = fundamentals_service.get_enrichment_bulk([s["symbol"] for s in symbols_meta])
    items = []
    for meta in symbols_meta:
        symbol = meta["symbol"]
        for article in (enrichment.get(symbol.upper(), {}).get("recentNews") or []):
            items.append({
                "symbol": symbol,
                "title": article.get("title"),
                "publisher": article.get("publisher"),
                "published": article.get("published"),
                "link": article.get("link"),
                "summary": article.get("summary"),
            })
    # Rank by market reaction (relevance) blended with recency, not raw recency,
    # so a few heavily-covered names can't crowd out genuinely market-moving news.
    # Annotates each article with relevanceScore / reactionPct / sigma / direction.
    items = news_relevance_service.score_and_rank(items)

    # news_limit <= 0 means "return everything" so the scrollable feed can show the
    # full ranked list for auditing the algorithm.
    top_news = items if news_limit <= 0 else items[:news_limit]

    from datetime import datetime as _dt
    news_checked_at = _dt.now().strftime("%Y-%m-%dT%H:%M:%S")

    return jsonify({
        "recommendationChanges": changes,
        "recommendationChangesTotal": changes_total,
        "topNews": top_news,
        "newsCheckedAt": news_checked_at,
    })


@v1_bp.route("/assessments/overview", methods=["GET"])
def get_assessments_overview():
    """Portfolio-wide latest assessment per symbol (Summary overview panel)."""
    return jsonify({"assessments": assessment_service.latest_overview()})


@v1_bp.route("/track-record", methods=["GET"])
def get_track_record():
    """Read-only self-scoring of past recommendations and detected patterns.

    Evaluates any captures whose horizon has elapsed, then returns hit-rate
    buckets overall, by signal kind, and per recommendation/pattern label."""
    return jsonify(track_record_service.get_summary())


@v1_bp.route("/symbols/<symbol>/fundamentals", methods=["GET"])
def get_fundamentals(symbol):
    symbol_data = portfolio_service.get_symbol(symbol)
    if symbol_data is None:
        return jsonify({"error": f"Symbol {symbol.upper()} not found."}), 404
    enrichment = fundamentals_service.get_enrichment(symbol)
    return jsonify({
        "symbol": symbol.upper(),
        "currentPrice": symbol_data.get("currentPrice"),
        "dayChangePct": symbol_data.get("dayChangePct"),
        "fundamentals": enrichment.get("fundamentals", {}),
        "recentNews": enrichment.get("recentNews", []),
    })


@v1_bp.route("/news-relevance/<symbol>", methods=["GET"])
def get_news_relevance(symbol):
    """On-demand intraday (30-min) reaction scores for one symbol's recent news.

    Pulls the symbol's recent headlines and annotates each with an intraday
    relevance score, falling back to the Phase 1 daily score when intraday data
    isn't available for that article. Best-effort: never raises on scoring."""
    raw_news = fundamentals_service.fetch_recent_news(symbol) or []
    items = [
        {
            "symbol": symbol.upper(),
            "title": article.get("title"),
            "publisher": article.get("publisher"),
            "published": article.get("published"),
            "link": article.get("link"),
            "summary": article.get("summary"),
        }
        for article in raw_news
    ]
    annotated = news_relevance_service.score_symbol_intraday(symbol.upper(), items)
    return jsonify({"symbol": symbol.upper(), "news": annotated})


@v1_bp.route("/symbols/<symbol>/fib-levels", methods=["GET"])
def get_fib_levels(symbol):
    if portfolio_service.get_symbol(symbol) is None:
        return jsonify({"error": f"Symbol {symbol.upper()} not found."}), 404
    levels = fib_service.get_levels(symbol)
    if levels is None:
        return jsonify({"error": f"Could not compute Fibonacci levels for {symbol.upper()}."}), 404
    return jsonify(levels)


@v1_bp.route("/sync", methods=["POST"])
def sync_prices():
    result = portfolio_service.sync_prices(_engine())
    new_alerts = alerts_service.evaluate_all(_engine())
    active_alerts = alerts_service.list_alerts()
    return jsonify({
        "status": "success",
        "sync": result,
        "newAlerts": new_alerts,
        "alerts": active_alerts,
    })
