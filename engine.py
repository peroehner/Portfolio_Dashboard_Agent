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
        """Fetches live price and optionally analyst 1Y mean target per ticker.

        Uses the browser-impersonating Yahoo session when available. Bare
        ``yf.download`` without that session is frequently blocked from
        datacenter IPs (Render), which used to leave ``symbol_market`` stuck on
        the prior session close even after Sync Prices.
        """
        logging.info(
            "Engine fetching yfinance data for %s tickers (targets=%s)",
            len(tickers),
            include_analyst_targets,
        )
        if not tickers:
            return {}

        from services.company_name import resolve_company_name
        from services.market_cache import get_yf_session, reset_yf_session, yf_throttle

        day_changes = {ticker: None for ticker in tickers}
        prices = {ticker: None for ticker in tickers}
        price_as_of = {ticker: None for ticker in tickers}
        data = None
        multi = len(tickers) > 1
        session = get_yf_session()
        try:
            with yf_throttle():
                # Pass session so bulk download shares the curl_cffi crumb path.
                # threads=False: default True spins a ThreadPool per sync and
                # amplifies curl_cffi/native churn on the background price loop.
                data = yf.download(
                    tickers,
                    period="5d",
                    progress=False,
                    session=session,
                    threads=False,
                )
            if data is not None and not getattr(data, "empty", True):
                for ticker in tickers:
                    try:
                        closes = (
                            data["Close"][ticker].dropna()
                            if multi
                            else data["Close"].dropna()
                        )
                        parsed = self._quotes_from_closes(closes)
                        if parsed is None:
                            continue
                        prices[ticker] = parsed["price"]
                        price_as_of[ticker] = parsed["priceAsOf"]
                        day_changes[ticker] = parsed["dayChangePct"]
                    except (KeyError, IndexError, TypeError):
                        prices[ticker] = None
        except Exception as e:
            logging.error(f"Failed to fetch market prices: {e}")
            reset_yf_session()
        finally:
            data = None

        missing = [ticker for ticker in tickers if prices.get(ticker) is None]
        if missing:
            self._fill_quotes_from_history(missing, prices, price_as_of, day_changes)

        # Daily bars often lag the open by a long time. During US RTH, when history
        # is still prior session, pull a short intraday print so Sync isn't stuck
        # on yesterday's close for ~an hour.
        self._apply_intraday_session_catchup(tickers, prices, price_as_of, day_changes)

        quotes = {}
        for ticker in tickers:
            info = self._fetch_ticker_info(ticker)
            analyst_targets = (
                self._analyst_targets_from_info(info)
                if include_analyst_targets
                else {"mean": None, "low": None, "high": None}
            )
            price = prices[ticker]
            as_of = price_as_of.get(ticker)
            day_pct = day_changes.get(ticker)
            info_price, info_as_of = self._price_as_of_from_info(info)
            # Datacenter Yahoo chart feeds sometimes omit the latest US session
            # (history ends prior day) while quoteSummary already has that close.
            # Prefer the newer info quote so Sync cannot rewrite stale closes.
            if self._should_prefer_info_quote(info, as_of, info_as_of, price, info_price):
                logging.info(
                    "Using newer quoteSummary for %s (history asOf=%s → info asOf=%s)",
                    ticker,
                    as_of,
                    info_as_of,
                )
                price = info_price
                as_of = info_as_of or self._ny_session_date_today()
                day_pct = self._day_change_pct_from_info(info, price)
            elif price is None:
                price, as_of = info_price, info_as_of
            if day_pct is None:
                day_pct = self._day_change_pct_from_info(info, price)
            company_name = resolve_company_name(ticker, info)
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
                "priceAsOf": as_of,
            }
        return quotes

    @staticmethod
    def _ny_now():
        from datetime import datetime
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("America/New_York"))

    @classmethod
    def _ny_session_date_today(cls) -> str:
        return cls._ny_now().strftime("%Y-%m-%d")

    @classmethod
    def _in_us_regular_hours(cls) -> bool:
        """True during the US cash session (Mon–Fri 09:30–16:00 America/New_York)."""
        now = cls._ny_now()
        if now.weekday() >= 5:
            return False
        minutes = now.hour * 60 + now.minute
        return (9 * 60 + 30) <= minutes <= (16 * 60)

    @classmethod
    def _intraday_catchup_enabled(cls) -> bool:
        return os.environ.get("YF_INTRADAY_CATCHUP", "1").lower() not in (
            "0",
            "false",
            "no",
            "off",
        )

    def _apply_intraday_session_catchup(self, tickers, prices, price_as_of, day_changes):
        """During RTH, replace lagging daily closes with today's intraday last print."""
        if not self._intraday_catchup_enabled() or not self._in_us_regular_hours():
            return
        today = self._ny_session_date_today()
        lagging = [
            ticker
            for ticker in tickers
            if (price_as_of.get(ticker) or "") < today
        ]
        if not lagging:
            return

        from services.market_cache import make_ticker, yf_pool

        interval = os.environ.get("YF_INTRADAY_CATCHUP_INTERVAL", "5m") or "5m"
        logging.info(
            "Intraday catch-up for %s symbols still on prior daily session (%s)",
            len(lagging),
            today,
        )

        def _one(symbol: str):
            try:
                hist = make_ticker(symbol).history(
                    period="1d",
                    interval=interval,
                    auto_adjust=True,
                )
            except Exception as exc:  # noqa: BLE001
                logging.warning("Intraday catch-up failed for %s: %s", symbol, exc)
                return symbol, None
            if hist is None or getattr(hist, "empty", True) or "Close" not in hist.columns:
                # Yahoo logs "possibly delisted" for OTC/foreign names with no
                # 1d bars — treat as a quiet miss, not a sync failure.
                return symbol, None
            closes = hist["Close"].dropna()
            if closes.empty:
                return symbol, None
            as_of = self._session_date_from_index(closes.index[-1]) or today
            # Reject bars that still don't reach today's session.
            if as_of < today:
                return symbol, None
            return symbol, {
                "price": float(closes.iloc[-1]),
                "priceAsOf": as_of,
            }

        updated = 0
        for symbol, parsed in yf_pool.map(_one, lagging):
            if not parsed:
                continue
            prior = prices.get(symbol)
            live = parsed["price"]
            prices[symbol] = live
            price_as_of[symbol] = parsed["priceAsOf"]
            if prior is not None and float(prior):
                day_changes[symbol] = round((live - float(prior)) / float(prior) * 100, 2)
            updated += 1
        if updated:
            logging.info("Intraday catch-up updated %s / %s symbols", updated, len(lagging))

    @staticmethod
    def _info_has_live_rth_print(info: dict, info_price: float | None, info_as_of: str | None) -> bool:
        """True when quoteSummary looks like a real cash-session print (not idle stamp)."""
        if info_price is None or not info:
            return False
        state = str(info.get("marketState") or "").upper()
        if state not in ("REGULAR", "POST", "POSTPOST"):
            return False
        today = PortfolioEngine._ny_session_date_today()
        if info_as_of and info_as_of < today:
            return False
        try:
            prev = info.get("previousClose") or info.get("regularMarketPreviousClose")
            if prev is not None and abs(float(info_price) - float(prev)) > 0.05:
                return True
        except (TypeError, ValueError):
            pass
        try:
            volume = info.get("regularMarketVolume")
            if volume is not None and int(volume) > 0 and (info_as_of is None or info_as_of >= today):
                # Volume alone is weak evidence; require today's stamp when present.
                if info_as_of is None or info_as_of == today:
                    change = info.get("regularMarketChange")
                    if change is not None and abs(float(change)) > 0.01:
                        return True
        except (TypeError, ValueError):
            pass
        return False

    @classmethod
    def _should_prefer_info_quote(
        cls,
        info: dict,
        hist_as_of: str | None,
        info_as_of: str | None,
        hist_price: float | None,
        info_price: float | None,
    ) -> bool:
        if cls._info_quote_is_newer(hist_as_of, info_as_of, hist_price, info_price):
            return True
        # After the open, daily history may still be prior close while quoteSummary
        # already has a live RTH print vs previousClose.
        if not cls._in_us_regular_hours():
            return False
        today = cls._ny_session_date_today()
        if hist_as_of and hist_as_of >= today:
            return False
        return cls._info_has_live_rth_print(info, info_price, info_as_of)

    @staticmethod
    def _session_date_from_index(ts) -> str | None:
        """Calendar date of a history bar in America/New_York (US equity session)."""
        try:
            from zoneinfo import ZoneInfo

            # pandas Timestamp / datetime — normalize tz-aware bars to NY so a
            # UTC midnight label cannot drift the displayed session date.
            if hasattr(ts, "tz_convert"):
                if getattr(ts, "tz", None) is not None or getattr(ts, "tzinfo", None) is not None:
                    ts = ts.tz_convert(ZoneInfo("America/New_York"))
                return ts.strftime("%Y-%m-%d")
            if hasattr(ts, "astimezone") and getattr(ts, "tzinfo", None) is not None:
                return ts.astimezone(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
            return ts.strftime("%Y-%m-%d")
        except (AttributeError, ValueError, TypeError):
            return None

    @staticmethod
    def _quotes_from_closes(closes):
        """Map a Close series to price / as-of / day%."""
        if closes is None or getattr(closes, "empty", True):
            return None
        price = float(closes.iloc[-1])
        as_of = PortfolioEngine._session_date_from_index(closes.index[-1])
        day_pct = None
        if len(closes) >= 2:
            previous = float(closes.iloc[-2])
            if previous:
                day_pct = round((price - previous) / previous * 100, 2)
        return {"price": price, "priceAsOf": as_of, "dayChangePct": day_pct}

    def _fill_quotes_from_history(self, tickers, prices, price_as_of, day_changes):
        """Per-symbol history via the impersonating session (download fallback)."""
        from services.market_cache import make_ticker, yf_pool

        def _one(symbol: str):
            try:
                hist = make_ticker(symbol).history(period="5d", auto_adjust=True)
            except Exception as exc:  # noqa: BLE001
                logging.warning("History fallback failed for %s: %s", symbol, exc)
                return symbol, None
            if hist is None or getattr(hist, "empty", True) or "Close" not in hist.columns:
                return symbol, None
            return symbol, self._quotes_from_closes(hist["Close"].dropna())

        for symbol, parsed in yf_pool.map(_one, tickers):
            if not parsed:
                continue
            prices[symbol] = parsed["price"]
            price_as_of[symbol] = parsed["priceAsOf"]
            day_changes[symbol] = parsed["dayChangePct"]

    @staticmethod
    def _price_as_of_from_info(info: dict) -> tuple[float | None, str | None]:
        """Price + session date from quoteSummary (regularMarket*)."""
        if not info:
            return None, None
        raw = info.get("regularMarketPrice") or info.get("currentPrice")
        if raw is None:
            return None, None
        try:
            price = float(raw)
        except (TypeError, ValueError):
            return None, None
        as_of = None
        ts = info.get("regularMarketTime")
        if ts is not None:
            try:
                from datetime import datetime
                from zoneinfo import ZoneInfo

                as_of = datetime.fromtimestamp(
                    int(ts), tz=ZoneInfo("America/New_York")
                ).strftime("%Y-%m-%d")
            except Exception:  # noqa: BLE001
                as_of = None
        return price, as_of

    @staticmethod
    def _info_quote_is_newer(
        hist_as_of: str | None,
        info_as_of: str | None,
        hist_price: float | None,
        info_price: float | None,
    ) -> bool:
        """True when quoteSummary reflects a newer traded session than daily history.

        Yahoo often advances ``regularMarketTime`` to "today" while
        ``regularMarketPrice`` is still the prior close (premarket / idle stamp).
        Advancing ``priceAsOf`` in that case makes the UI promise a newer data
        session than the numbers can live up to — only prefer info when the
        price print itself moved (or history has no price yet).
        """
        if info_price is None:
            return False
        price_moved = hist_price is None or abs(float(info_price) - float(hist_price)) > 0.05
        if info_as_of and (hist_as_of is None or info_as_of > hist_as_of):
            return price_moved
        if info_as_of and hist_as_of == info_as_of and price_moved:
            # Same calendar label but history bar disagrees with the live quote.
            return True
        return False

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
