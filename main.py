# Main entry point for the application
import os
import platform
import socket
import subprocess
import threading
import time
import logging
import urllib.error
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def load_env_file() -> None:
    """Load .env before service imports so API keys are available."""
    env_path = BASE_DIR / ".env"
    if not env_path.is_file():
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_path)
    except ImportError:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


load_env_file()

from flask import Flask, jsonify, send_file, request

from api.v1 import v1_bp
from db.database import init_db
from services.alerts_service import AlertsService
from services.import_service import ImportService
from services.portfolio_service import PortfolioService

app = Flask(__name__, static_folder=str(BASE_DIR))
app.register_blueprint(v1_bp)

portfolio_service = PortfolioService()
alerts_service = AlertsService()
import_service = ImportService()
engine = None
_sync_worker_started = False
_sync_worker_lock = threading.Lock()


def get_engine():
    """Load the AI engine lazily so Flask can bind before heavy model init."""
    global engine
    if engine is None:
        from engine import PortfolioEngine
        engine = PortfolioEngine()
    return engine


def background_sync_loop():
    """Background worker that continuously syncs prices via the engine."""
    cycle = 0
    target_refresh_every = max(
        1,
        int(os.environ.get("TARGET_REFRESH_CYCLES", "12")),
    )
    while True:
        symbols = portfolio_service.list_symbols()
        if symbols:
            cycle += 1
            refresh_targets = cycle % target_refresh_every == 0
            logging.info(
                "Background Sync: Fetching data for %s assets (targets=%s).",
                len(symbols),
                refresh_targets,
            )
            result = portfolio_service.sync_prices(
                get_engine(),
                refresh_targets=refresh_targets,
            )
            new_alerts = alerts_service.evaluate_all(get_engine())
            if new_alerts:
                logging.info(f"New alerts: {[alert['message'] for alert in new_alerts]}")
            logging.info(f"Background Sync Complete. Updated {result['updated']} assets.")
        time.sleep(300)


def ensure_background_worker():
    """Start price sync worker once (works under gunicorn and dev server)."""
    global _sync_worker_started
    with _sync_worker_lock:
        if not _sync_worker_started:
            worker = threading.Thread(target=background_sync_loop, daemon=True)
            worker.start()
            _sync_worker_started = True


@app.before_request
def handle_options():
    if request.method == "OPTIONS":
        return "", 204


@app.before_request
def ensure_database():
    if not getattr(app, "_db_ready", False):
        init_db()
        app._db_ready = True
    ensure_background_worker()


@app.after_request
def add_cors_headers(response):
    """Allow browser/API access through ngrok and other cross-origin frontends."""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, ngrok-skip-browser-warning"
    return response


@app.route("/health")
def health():
    """Simple readiness check for deployment/ngrok verification."""
    from services.llm_client import LLMClient

    client = LLMClient()
    return jsonify({
        "status": "ok",
        "version": "1.0",
        "api": "/api/v1",
        "assessmentProvider": client.active_provider(),
    })


@app.route("/")
def serve_dashboard():
    """Serves the frontend layout."""
    dashboard_path = BASE_DIR / "dashboard.html"
    if not dashboard_path.is_file():
        return jsonify({"status": "error", "message": "dashboard.html not found"}), 404
    return send_file(dashboard_path)


@app.route("/api/sync", methods=["GET"])
def trigger_manual_sync():
    """Legacy endpoint — refreshes prices and returns portfolio state."""
    if not portfolio_service.list_symbols():
        return jsonify({"status": "error", "message": "No portfolio data loaded in backend."}), 400

    portfolio_service.sync_prices(get_engine())
    symbols = {item["symbol"]: item for item in portfolio_service.list_symbols()}
    return jsonify({"status": "success", "data": symbols})


@app.route("/api/state", methods=["POST", "OPTIONS"])
def update_state():
    """Legacy endpoint — bulk import portfolio JSON into SQLite."""
    if request.method == "OPTIONS":
        return "", 204

    state = request.get_json(silent=True) or {}
    mode = request.args.get("mode") or state.pop("mode", None) or "merge"
    try:
        result = import_service.import_payload(state, mode=mode)
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
    return jsonify({
        "status": "success",
        "message": "Backend state updated.",
        "count": result["symbolsImported"],
        "symbolsImported": result["symbolsImported"],
        "holdingsImported": result["holdingsImported"],
    })


@app.route("/docs/api")
def serve_api_docs():
    docs_path = BASE_DIR / "docs" / "API.md"
    if not docs_path.is_file():
        return jsonify({"error": "API documentation not found."}), 404
    return send_file(docs_path, mimetype="text/markdown; charset=utf-8")


@app.route("/docs/replit")
def serve_replit_docs():
    docs_path = BASE_DIR / "docs" / "REPLIT.md"
    if not docs_path.is_file():
        return jsonify({"error": "Replit guide not found."}), 404
    return send_file(docs_path, mimetype="text/markdown; charset=utf-8")


@app.route("/<path:asset_path>")
def serve_assets(asset_path):
    """Serve supporting static assets such as the saved-page _files folder."""
    if asset_path.startswith("api/"):
        return jsonify({"status": "error", "message": "API route not found"}), 404

    file_path = (BASE_DIR / asset_path).resolve()
    if not file_path.is_file() or BASE_DIR not in file_path.parents:
        return jsonify({"status": "error", "message": "Not found"}), 404
    return send_file(file_path)


def port_is_available(port):
    """Return True if the app can bind to this port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


def free_port(port):
    """Best-effort release of a stale listener before redeploying."""
    try:
        if platform.system() == "Darwin":
            subprocess.run(
                ["bash", "-c", f"lsof -ti tcp:{port} | xargs kill -9 2>/dev/null || true"],
                check=False,
            )
        else:
            subprocess.run(["fuser", "-k", f"{port}/tcp"], check=False, capture_output=True)
        time.sleep(0.5)
        logging.info(f"Cleared stale process on port {port}")
    except FileNotFoundError:
        logging.warning(f"Could not auto-clear port {port}; stop the old server manually or set PORT.")


def resolve_port(requested=None):
    """Pick an open port; macOS AirPlay often blocks 5000."""
    if requested is not None:
        preferred = [int(requested)]
    elif os.environ.get("PORT"):
        preferred = [int(os.environ["PORT"])]
    else:
        preferred = [5000]

    candidates = preferred + [p for p in range(5000, 5010) if p not in preferred]

    if os.environ.get("FREE_PORT", "1").lower() in ("1", "true", "yes"):
        free_port(preferred[0])

    for port in candidates:
        if port_is_available(port):
            if port != preferred[0]:
                logging.warning("Port %s is in use. Using port %s instead.", preferred[0], port)
            return port

    raise RuntimeError(
        f"No available port found (tried {candidates[0]}–{candidates[-1]}). "
        "Stop the old server or set PORT to a free port."
    )


def wait_until_ready(port, timeout=120):
    """Block until the Flask health endpoint responds locally."""
    deadline = time.time() + timeout
    health_url = f"http://127.0.0.1:{port}/health"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=2) as response:
                if response.status == 200:
                    logging.info(f"Server ready at {health_url}")
                    return health_url
        except (urllib.error.URLError, TimeoutError):
            time.sleep(1)
    raise TimeoutError(f"Server did not become ready on port {port} within {timeout}s")


def start_server(port=None, block=True, wait_timeout=120):
    """Start Flask; use block=False in notebooks before opening an ngrok tunnel."""
    logging.basicConfig(level=logging.INFO)
    port = resolve_port(port)

    init_db()
    ensure_background_worker()

    run_kwargs = {
        "debug": os.environ.get("FLASK_DEBUG", "0").lower() in ("1", "true", "yes"),
        "port": port,
        "host": "0.0.0.0",
        "threaded": True,
        "use_reloader": False,
    }

    print(f"Starting Portfolio Agent Server on http://0.0.0.0:{port}")
    print(f"Dashboard: http://127.0.0.1:{port}/")
    if block:
        try:
            app.run(**run_kwargs)
        except OSError as exc:
            if getattr(exc, "errno", None) != 48:
                raise
            fallback = resolve_port(port + 1 if port < 5009 else 5001)
            logging.warning("Port %s failed to bind (%s). Retrying on %s.", port, exc, fallback)
            run_kwargs["port"] = fallback
            print(f"Retrying on http://127.0.0.1:{fallback}/")
            app.run(**run_kwargs)
        return None

    server_thread = threading.Thread(target=lambda: app.run(**run_kwargs), daemon=True)
    server_thread.start()
    return wait_until_ready(port, timeout=wait_timeout)


if __name__ == "__main__":
    start_server()
