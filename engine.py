import logging
import os

import yfinance as yf

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

class PortfolioEngine:
    def __init__(self):
        self.sentiment_analyzer = None
        if os.environ.get("SKIP_TRANSFORMERS", "").lower() in ("1", "true", "yes"):
            logging.info("Skipping transformers (SKIP_TRANSFORMERS=1).")
            return

        logging.info("Initializing AI components (PyTorch & Transformers)...")
        try:
            import torch
            from transformers import pipeline

            self.sentiment_analyzer = pipeline(
                "sentiment-analysis",
                model="distilbert-base-uncased-finetuned-sst-2-english",
                device=0 if torch.cuda.is_available() else -1,
            )
        except Exception as e:
            logging.warning(f"Transformers unavailable (running in data-only mode): {e}")
            
    def fetch_market_data(self, tickers):
        """Fetches live market data using yfinance."""
        quotes = self.fetch_market_quotes(tickers)
        return {ticker: quote.get("currentPrice") for ticker, quote in quotes.items()}

    def fetch_market_quotes(self, tickers, *, include_analyst_targets: bool = True):
        """Fetches live price and optionally analyst 1Y mean target per ticker."""
        logging.info(
            "Engine fetching yfinance data for %s tickers (targets=%s)",
            len(tickers),
            include_analyst_targets,
        )
        if not tickers:
            return {}

        from services.market_cache import yf_throttle

        day_changes = {ticker: None for ticker in tickers}
        prices = {ticker: None for ticker in tickers}
        price_as_of = {ticker: None for ticker in tickers}
        data = None
        multi = len(tickers) > 1
        try:
            with yf_throttle():
                data = yf.download(tickers, period="5d", progress=False)
            for ticker in tickers:
                try:
                    closes = (
                        data["Close"][ticker].dropna()
                        if multi
                        else data["Close"].dropna()
                    )
                    if closes.empty:
                        continue
                    price = float(closes.iloc[-1])
                    prices[ticker] = price
                    try:
                        price_as_of[ticker] = closes.index[-1].strftime("%Y-%m-%d")
                    except (AttributeError, ValueError, TypeError):
                        price_as_of[ticker] = None
                    if len(closes) >= 2:
                        previous = float(closes.iloc[-2])
                        if previous:
                            day_changes[ticker] = round((price - previous) / previous * 100, 2)
                except (KeyError, IndexError, TypeError):
                    prices[ticker] = None
        except Exception as e:
            logging.error(f"Failed to fetch market prices: {e}")
        finally:
            data = None

        quotes = {}
        for ticker in tickers:
            info = self._fetch_ticker_info(ticker)
            analyst_targets = (
                self._analyst_targets_from_info(info)
                if include_analyst_targets
                else {"mean": None, "low": None, "high": None}
            )
            price = prices[ticker]
            day_pct = day_changes.get(ticker)
            if day_pct is None:
                day_pct = self._day_change_pct_from_info(info, price)
            company_name = info.get("longName") or info.get("shortName")
            quotes[ticker] = {
                "currentPrice": (
                    round(float(price), 2)
                    if price is not None
                    else None
                ),
                "dayChangePct": day_pct,
                "analystTarget1y": analyst_targets["mean"],
                "analystTargetLow": analyst_targets["low"],
                "analystTargetHigh": analyst_targets["high"],
                "companyName": company_name,
                "priceAsOf": price_as_of.get(ticker),
            }
        return quotes

    def _fetch_ticker_info(self, ticker: str) -> dict:
        from services.market_cache import make_ticker, ticker_info_cache

        try:
            return ticker_info_cache.get(ticker.upper(), lambda: make_ticker(ticker).info) or {}
        except Exception as e:
            logging.warning(f"Failed to fetch ticker info for {ticker}: {e}")
            return {}

    def _day_change_pct_from_info(self, info: dict, price: float | None) -> float | None:
        try:
            pct = info.get("regularMarketChangePercent")
            if pct is not None:
                return round(float(pct), 2)
            previous_close = info.get("previousClose") or info.get("regularMarketPreviousClose")
            market_price = price
            if market_price is None:
                raw = info.get("regularMarketPrice") or info.get("currentPrice")
                market_price = float(raw) if raw is not None else None
            if market_price is not None and previous_close:
                previous_close = float(previous_close)
                if previous_close:
                    return round((float(market_price) - previous_close) / previous_close * 100, 2)
            change = info.get("regularMarketChange")
            if change is not None and previous_close:
                return round(float(change) / float(previous_close) * 100, 2)
        except Exception as e:
            logging.warning(f"Failed to parse day change from info: {e}")
        return None

    def _analyst_targets_from_info(self, info: dict) -> dict[str, float | None]:
        result: dict[str, float | None] = {"mean": None, "low": None, "high": None}
        try:
            for key, field in (
                ("mean", "targetMeanPrice"),
                ("low", "targetLowPrice"),
                ("high", "targetHighPrice"),
            ):
                value = info.get(field)
                if value is not None:
                    result[key] = round(float(value), 2)
        except Exception as e:
            logging.warning(f"Failed to parse analyst targets from info: {e}")
        return result

    def _fetch_day_change_pct(self, ticker: str, price: float | None) -> float | None:
        """Session day change from yfinance info (works on non-trading days via last close)."""
        return self._day_change_pct_from_info(self._fetch_ticker_info(ticker), price)

    def _fetch_analyst_target(self, ticker: str) -> float | None:
        return self._fetch_analyst_targets(ticker)["mean"]

    def _fetch_analyst_targets(self, ticker: str) -> dict[str, float | None]:
        """Analyst 1Y target mean/low/high from the cached yfinance info."""
        return self._analyst_targets_from_info(self._fetch_ticker_info(ticker))

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
            target = details.get("analystTarget1y") or details.get("targetPrice", 0)
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
