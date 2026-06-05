import threading
import time
import logging
from pathlib import Path

from flask import Flask, jsonify, send_file, request
from engine import PortfolioEngine

BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__, static_folder=str(BASE_DIR))
engine = PortfolioEngine()

# In-memory store mirroring the frontend's loaded assets
portfolio_state = {}

def background_sync_loop():
    """Background worker that continuously syncs prices via the engine."""
    while True:
        if portfolio_state:
            tickers = list(portfolio_state.keys())
            logging.info(f"Background Sync: Fetching data for {len(tickers)} assets.")
            
            # Fetch live prices via yfinance
            live_prices = engine.fetch_market_data(tickers)
            
            updated_count = 0
            for ticker, price in live_prices.items():
                if price is not None:
                    portfolio_state[ticker]["currentPrice"] = price
                    updated_count += 1
                    
            # AI Screener
            alerts = engine.run_screener(portfolio_state)
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
    live_prices = engine.fetch_market_data(tickers)
    
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

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Start the autonomous background sync loop
    worker = threading.Thread(target=background_sync_loop, daemon=True)
    worker.start()
    
    # Start the Flask web application
    print("Starting Portfolio Agent Server on http://0.0.0.0:5000")
    app.run(debug=True, port=5000, host="0.0.0.0", threaded=True, use_reloader=False)
