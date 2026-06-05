import yfinance as yf
import torch
from transformers import pipeline
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

class PortfolioEngine:
    def __init__(self):
        logging.info("Initializing AI components (PyTorch & Transformers)...")
        try:
            self.sentiment_analyzer = pipeline(
                "sentiment-analysis", 
                model="distilbert-base-uncased-finetuned-sst-2-english",
                device=0 if torch.cuda.is_available() else -1
            )
        except Exception as e:
            logging.warning(f"Transformers initialization failed (running in data-only mode): {e}")
            self.sentiment_analyzer = None
            
    def fetch_market_data(self, tickers):
        """Fetches live market data using yfinance."""
        logging.info(f"Engine fetching yfinance data for: {tickers}")
        if not tickers:
            return {}
        try:
            data = yf.download(tickers, period="1d", progress=False)
            prices = {}
            for ticker in tickers:
                try:
                    if len(tickers) == 1:
                        prices[ticker] = float(data['Close'].iloc[-1])
                    else:
                        prices[ticker] = float(data['Close'][ticker].iloc[-1])
                except (KeyError, IndexError, TypeError):
                    prices[ticker] = None
            return prices
        except Exception as e:
            logging.error(f"Failed to fetch market data: {e}")
            return {ticker: None for ticker in tickers}

    def analyze_asset_sentiment(self, texts):
        """AI analysis of stock news or fundamental text."""
        if self.sentiment_analyzer and texts:
            try:
                return self.sentiment_analyzer(texts)
            except Exception as e:
                logging.error(f"Error running sentiment analysis pipeline: {e}")
        return [{"label": "NEUTRAL", "score": 0.5} for _ in texts]

    def run_screener(self, portfolio_data):
        """Filters and screens for actionable portfolio alerts."""
        alerts = []
        for symbol, details in portfolio_data.items():
            price = details.get("currentPrice", 0)
            target = details.get("targetPrice", 0)
            if target and price:
                upside = (target - price) / price
                if upside > 0.30:
                    alerts.append(f"{symbol} trades at a {upside*100:.1f}% discount to 1Y target.")
        return alerts

def run_pipeline(portfolio_data=None):
    """Module-level entry point to run the complete pipeline."""
    logging.info("Starting Pipeline Execution...")
    if portfolio_data is None:
        portfolio_data = {
            "AAPL": {"currentPrice": 311.33, "targetPrice": 308.65},
            "AMZN": {"currentPrice": 263.86, "targetPrice": 312.63},
            "INTC": {"currentPrice": 122.70, "targetPrice": 87.86},
            "GOOG": {"currentPrice": 382.29, "targetPrice": 417.94},
            "NET": {"currentPrice": 218.60, "targetPrice": 234.18}
        }
    
    engine = PortfolioEngine()
    tickers = list(portfolio_data.keys())
    
    logging.info("Pipeline Step 1: Fetching Market Prices...")
    live_prices = engine.fetch_market_data(tickers)
    for ticker, price in live_prices.items():
        if price is not None:
            portfolio_data[ticker]["currentPrice"] = price

    logging.info("Pipeline Step 2: Running Portfolio Screener...")
    alerts = engine.run_screener(portfolio_data)

    logging.info("Pipeline Step 3: Conducting Sentiment Audit...")
    sample_headlines = [f"Institutional flow remains highly supportive for {t}" for t in tickers]
    sentiments = engine.analyze_asset_sentiment(sample_headlines)
    
    results = {}
    for ticker, sentiment in zip(tickers, sentiments):
        results[ticker] = {
            "price": portfolio_data[ticker].get("currentPrice"),
            "target": portfolio_data[ticker].get("targetPrice"),
            "sentiment": sentiment
        }

    logging.info("Pipeline Execution Successfully Completed.")
    return {
        "portfolio_state": portfolio_data,
        "alerts": alerts,
        "metrics": results
    }
