import logging
import os

from flask import Blueprint, jsonify, request

from api.openapi_spec import OPENAPI_SPEC
from services.alerts_service import AlertsService
from services.assessment_service import AssessmentService
from services.fib_service import FibService
from services.fundamentals_service import FundamentalsService
from services.holdings_service import HoldingsService
from services.import_service import ImportService
from services.inspector_service import InspectorService
from services.notes_service import NotesService
from services.overview_service import OverviewService
from services.portfolio_service import PortfolioService
from services.screening_service import ScreeningService
from services.technical_service import TechnicalService
from services.llm_client import LLMClient

v1_bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")

portfolio_service = PortfolioService()
notes_service = NotesService()
alerts_service = AlertsService()
fib_service = FibService()
assessment_service = AssessmentService()
holdings_service = HoldingsService()
import_service = ImportService()
overview_service = OverviewService()
screening_service = ScreeningService()
inspector_service = InspectorService()
fundamentals_service = FundamentalsService()
technical_service = TechnicalService()


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
    from db.database import get_current_user_id, get_prefer_computed_trends, get_user

    user = get_user(get_current_user_id())
    return jsonify({
        "authEnabled": AUTH_ENABLED,
        "preferComputedTrends": get_prefer_computed_trends(),
        "user": {
            "id": user["id"],
            "email": user["email"],
            "name": user["name"],
            "picture": user["picture"],
        } if user else None,
    })


@v1_bp.route("/preferences", methods=["PATCH"])
def update_preferences():
    """Update per-user preferences (currently: prefer computed trends over imported TA)."""
    from db.database import get_prefer_computed_trends, set_prefer_computed_trends

    data = request.get_json(silent=True) or {}
    if "preferComputedTrends" in data:
        set_prefer_computed_trends(bool(data["preferComputedTrends"]))
    return jsonify({"preferComputedTrends": get_prefer_computed_trends()})


@v1_bp.route("/config", methods=["GET"])
def get_config():
    client = LLMClient()
    provider = client.active_provider()
    return jsonify({
        "version": "v1",
        "assessmentProvider": provider,
        "assessmentMode": client.mode,
        "llmConfigured": provider != "rules",
        "syncIntervalSeconds": 300,
        "fibProximityPct": float(os.environ.get("FIB_PROXIMITY_PCT", "1.0")),
        "importVersion": 8,
        "importModes": ["merge", "replace"],
        "features": {
            "noteSynthesis": True,
        },
        "synthesisGuidanceFromEnv": bool(client.synthesis_guidance),
        "geminiModel": client.gemini_model if client.active_provider() == "gemini" else None,
        "docs": {
            "api": "/docs/api",
            "replit": "/docs/replit",
            "openapi": "/api/v1/openapi.json",
        },
    })


@v1_bp.route("/openapi.json", methods=["GET"])
def openapi_spec():
    return jsonify(OPENAPI_SPEC)


@v1_bp.route("/symbols", methods=["GET"])
def list_symbols():
    return jsonify({"symbols": portfolio_service.list_symbols()})


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
    item = portfolio_service.upsert_symbol(symbol, data)
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
    return jsonify(holding), 201


@v1_bp.route("/holdings/<symbol>", methods=["PUT"])
def update_holding(symbol):
    data = request.get_json(silent=True) or {}
    holding = holdings_service.upsert_holding(symbol, data)
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
    return jsonify({"results": screening_service.fib_proximity_map()})


@v1_bp.route("/symbols/<symbol>/inspector", methods=["GET"])
def inspect_symbol(symbol):
    result = inspector_service.inspect(symbol)
    if result is None:
        return jsonify({"error": f"Symbol {symbol.upper()} not found."}), 404
    return jsonify(result)


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
    symbols_meta = portfolio_service.list_symbols()
    enrichment = fundamentals_service.get_enrichment_bulk([s["symbol"] for s in symbols_meta])
    rows = []
    for meta in symbols_meta:
        symbol = meta["symbol"]
        data = enrichment.get(symbol.upper(), {})
        rows.append({
            "symbol": symbol,
            "currentPrice": meta.get("currentPrice"),
            "dayChangePct": meta.get("dayChangePct"),
            "fundamentals": data.get("fundamentals", {}),
            "recentNews": data.get("recentNews", []),
        })
    return jsonify({"symbols": rows})


@v1_bp.route("/news-feed", methods=["GET"])
def news_feed():
    """Compact Summary feed: latest recommendation changes + top recent news."""
    news_limit = request.args.get("newsLimit", default=8, type=int)
    changes_limit = request.args.get("changesLimit", default=6, type=int)

    changes = assessment_service.list_recommendation_changes(limit=changes_limit)

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
    # Newest first; fall back to stable order when dates are missing/equal.
    items.sort(key=lambda a: (a.get("published") or ""), reverse=True)

    return jsonify({
        "recommendationChanges": changes,
        "topNews": items[: max(0, news_limit)],
    })


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
