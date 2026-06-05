import os
import platform
import subprocess
import threading
import time
import logging
import urllib.error
import urllib.request
from pathlib import Path

from flask import Flask, jsonify, send_file, request

BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__, static_folder=str(BASE_DIR))
engine = None

def get_engine():
    """Load the AI engine lazily so Flask can bind before heavy model init."""
    global engine
    if engine is None:
        from engine import PortfolioEngine
        engine = PortfolioEngine()
    return engine

# In-memory store mirroring the frontend's loaded assets
portfolio_state = {}

def background_sync_loop():
    """Background worker that continuously syncs prices via the engine."""
    while True:
        if portfolio_state:
            tickers = list(portfolio_state.keys())
            logging.info(f"Background Sync: Fetching data for {len(tickers)} assets.")
            
            # Fetch live prices via yfinance
            live_prices = get_engine().fetch_market_data(tickers)
            
            updated_count = 0
            for ticker, price in live_prices.items():
                if price is not None:
                    portfolio_state[ticker]["currentPrice"] = price
                    updated_count += 1
                    
            # AI Screener
            alerts = get_engine().run_screener(portfolio_state)
            if alerts:
                logging.info(f"AI Screener Alerts: {alerts}")
                
            logging.info(f"Background Sync Complete. Updated {updated_count} assets.")
            
        time.sleep(300)  # Sleep for 5 minutes

@app.after_request
def add_cors_headers(response):
    """Allow browser/API access through ngrok and other cross-origin frontends."""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, ngrok-skip-browser-warning"
    return response

@app.route("/health")
def health():
    """Simple readiness check for deployment/ngrok verification."""
    return jsonify({"status": "ok"})

@app.route("/")
def serve_dashboard():
    """Serves the frontend layout."""
    dashboard_path = BASE_DIR / "dashboard.html"
    if not dashboard_path.is_file():
        return jsonify({"status": "error", "message": "dashboard.html not found"}), 404
    return send_file(dashboard_path)

@app.route("/api/sync", methods=["GET"])
def trigger_manual_sync():
    """Endpoint for the frontend to request an immediate data sync."""
    if not portfolio_state:
        return jsonify({"status": "error", "message": "No portfolio data loaded in backend."}), 400
        
    tickers = list(portfolio_state.keys())
    live_prices = get_engine().fetch_market_data(tickers)

    for ticker, price in live_prices.items():
        if price is not None:
            portfolio_state[ticker]["currentPrice"] = price

    return jsonify({"status": "success", "data": portfolio_state})

@app.route("/api/state", methods=["POST", "OPTIONS"])
def update_state():
    """Allows frontend to push parsed file data to the backend engine."""
    if request.method == "OPTIONS":
        return "", 204

    global portfolio_state
    portfolio_state = request.json
    return jsonify({"status": "success", "message": "Backend state updated."})

@app.route("/<path:asset_path>")
def serve_assets(asset_path):
    """Serve supporting static assets such as the saved-page _files folder."""
    file_path = (BASE_DIR / asset_path).resolve()
    if not file_path.is_file() or BASE_DIR not in file_path.parents:
        return jsonify({"status": "error", "message": "Not found"}), 404
    return send_file(file_path)

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
    port = int(port or os.environ.get("PORT", 5000))

    if os.environ.get("FREE_PORT", "1").lower() in ("1", "true", "yes"):
        free_port(port)

    worker = threading.Thread(target=background_sync_loop, daemon=True)
    worker.start()

    run_kwargs = {
        "debug": os.environ.get("FLASK_DEBUG", "0").lower() in ("1", "true", "yes"),
        "port": port,
        "host": "0.0.0.0",
        "threaded": True,
        "use_reloader": False,
    }

    print(f"Starting Portfolio Agent Server on http://0.0.0.0:{port}")
    if block:
        app.run(**run_kwargs)
        return None

    server_thread = threading.Thread(target=lambda: app.run(**run_kwargs), daemon=True)
    server_thread.start()
    return wait_until_ready(port, timeout=wait_timeout)

if __name__ == "__main__":
    start_server()
