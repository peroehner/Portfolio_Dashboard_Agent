import yfinance as yf
import torch
from transformers import pipeline
import logging

class PortfolioEngine:
    def __init__(self):
        logging.info("Initializing AI components (PyTorch & Transformers)...")
        try:
            # Load a lightweight financial sentiment/analysis model
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
        try:
            # Group ticker fetch for performance
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
        if self.sentiment_analyzer:
            return self.sentiment_analyzer(texts)
        return []

    def run_screener(self, portfolio_data):
        """Filters and screens for actionable portfolio alerts."""
        alerts = []
        for symbol, details in portfolio_data.items():
            price = details.get("currentPrice", 0)
            target = details.get("targetPrice", 0)
            
            # Screening logic: Flag assets with >30% upside relative to mean targets
            if target and price:
                upside = (target - price) / price
                if upside > 0.30:
                    alerts.append(f"{symbol} trades at a {upside*100:.1f}% discount to 1Y target.")
        return alerts
