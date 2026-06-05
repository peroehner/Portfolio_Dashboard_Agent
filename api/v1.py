import os

from flask import Blueprint, jsonify, request

from api.openapi_spec import OPENAPI_SPEC
from services.alerts_service import AlertsService
from services.assessment_service import AssessmentService
from services.fib_service import FibService
from services.holdings_service import HoldingsService
from services.import_service import ImportService
from services.inspector_service import InspectorService
from services.notes_service import NotesService
from services.overview_service import OverviewService
from services.portfolio_service import PortfolioService
from services.screening_service import ScreeningService
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
    try:
        result = import_service.import_payload(payload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"status": "success", **result})


@v1_bp.route("/import/file", methods=["POST"])
def import_file():
    if "file" not in request.files:
        return jsonify({"error": "Upload a JSON or CSV file as 'file'."}), 400
    upload = request.files["file"]
    try:
        result = import_service.import_file(upload.filename or "upload.json", upload.read())
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"status": "success", **result})


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
    return jsonify({"status": "success", "assessments": assessments})


@v1_bp.route("/symbols/<symbol>/assess", methods=["POST"])
def assess_symbol(symbol):
    if portfolio_service.get_symbol(symbol) is None:
        return jsonify({"error": f"Symbol {symbol.upper()} not found."}), 404
    try:
        assessment = assessment_service.assess_symbol(symbol)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    return jsonify(assessment), 201


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
