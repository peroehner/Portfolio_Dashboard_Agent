import threading
import time
import logging
from flask import Flask, jsonify, send_file, request
from engine import PortfolioEngine

app = Flask(__name__, static_folder=".")
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
    """Serves the frontend layout."""
    return send_file("dashboard.html")

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
    logging.basicConfig(level=logging.INFO)
    
    # Start the autonomous background sync loop
    worker = threading.Thread(target=background_sync_loop, daemon=True)
    worker.start()
    
    # Start the Flask web application
    print("Starting Portfolio Agent Server on http://127.0.0.1:5000")
    app.run(debug=True, port=5000, use_reloader=False)

    # 1. Imports
#from engine import run_pipeline, generate_html
from engine import pipeline

def main():
    print("[PDA] Starting Portfolio Sync...")
    
    # Call the only function that exists in engine.py
    portfolio_data = engine.pipeline()
    
    # 2. Run the logic
    #portfolio_data = run_pipeline()
    
    # 3. Generate the static file
    #html_output = generate_html(portfolio_data)
    
    #with open("dashboard.html", "w", encoding="utf-8") as f:
    #    f.write(html_output)
    
    #print("[PDA] Success: dashboard.html generated.")

# 4. The "Entry Point" logic
# This ensures it runs when you execute 'python main.py' 
# but DOES NOT run automatically when you 'import main' in Colab.
if __name__ == "__main__":
    main()
