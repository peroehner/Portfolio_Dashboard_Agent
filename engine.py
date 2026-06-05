import os
import threading
import time
import logging
from flask import Flask, jsonify, send_file, request
from engine import PortfolioEngine

# Set up logging
logging.basicConfig(level=logging.INFO)

# Get the absolute directory of main.py to prevent working directory issues
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Configure Flask with absolute paths to ensure static file access works anywhere
app = Flask(__name__, static_folder=BASE_DIR, static_url_path="")
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

@app.route("/")
def serve_dashboard():
    """Serves the frontend layout, auto-detecting both dashboard.html and index.html."""
    for filename in ["dashboard.html", "index.html"]:
        path = os.path.join(BASE_DIR, filename)
        if os.path.exists(path):
            logging.info(f"Serving dashboard from: {path}")
            return send_file(path)
    
    # Elegant fallback error display instead of standard Flask 404/500 failures
    return (
        f"<div style='font-family: system-ui; max-width: 600px; margin: 100px auto; padding: 24px; border: 1px solid #e2e8f0; border-radius: 12px; background: #fff; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);'>"
        f"<h3 style='color: #ef4444; margin-top: 0;'>Portfolio Dashboard UI Not Found</h3>"
        f"<p style='color: #475569;'>Flask is running, but couldn't find your frontend HTML file. Please ensure either <b>dashboard.html</b> or <b>index.html</b> is placed inside the <code>Portfolio_Dashboard_Agent</code> directory:</p>"
        f"<p style='background: #f1f5f9; padding: 12px; border-radius: 6px; font-family: monospace; font-size: 13px; color: #0f172a;'>{BASE_DIR}</p>"
        f"</div>"
    ), 404

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

@app.route("/api/state", methods=["POST"])
def update_state():
    """Allows frontend to push parsed file data to the backend engine."""
    global portfolio_state
    portfolio_state = request.json
    return jsonify({"status": "success", "message": "Backend state updated."})

if __name__ == "__main__":
    # Start the autonomous background sync loop
    worker = threading.Thread(target=background_sync_loop, daemon=True)
    worker.start()
    
    # Start the Flask web application
    print("Starting Portfolio Agent Server on http://127.0.0.1:5000")
    app.run(debug=True, port=5000, use_reloader=False)
