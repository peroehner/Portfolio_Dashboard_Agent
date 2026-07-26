"""Unit tests for quote parsing and Sync Prices fallbacks (no live Yahoo)."""
from __future__ import annotations

import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pandas as pd

from engine import PortfolioEngine


class QuotesFromClosesTests(unittest.TestCase):
    def test_parses_last_close_and_day_change(self) -> None:
        idx = pd.to_datetime(["2026-07-23", "2026-07-24"])
        closes = pd.Series([190.01, 204.89], index=idx)
        parsed = PortfolioEngine._quotes_from_closes(closes)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertAlmostEqual(parsed["price"], 204.89)
        self.assertEqual(parsed["priceAsOf"], "2026-07-24")
        self.assertEqual(parsed["dayChangePct"], 7.83)

    def test_empty_closes_returns_none(self) -> None:
        self.assertIsNone(PortfolioEngine._quotes_from_closes(pd.Series(dtype=float)))


class PriceAsOfFromInfoTests(unittest.TestCase):
    def test_uses_regular_market_price_and_ny_date(self) -> None:
        ts = int(datetime(2026, 7, 24, 16, 0, tzinfo=ZoneInfo("America/New_York")).timestamp())
        price, as_of = PortfolioEngine._price_as_of_from_info(
            {"regularMarketPrice": 204.89, "regularMarketTime": ts}
        )
        self.assertEqual(price, 204.89)
        self.assertEqual(as_of, "2026-07-24")


class InfoQuoteNewerTests(unittest.TestCase):
    def test_prefers_info_when_history_session_lags(self) -> None:
        self.assertTrue(
            PortfolioEngine._info_quote_is_newer(
                "2026-07-23", "2026-07-24", 190.01, 204.89
            )
        )

    def test_keeps_history_when_same_session(self) -> None:
        self.assertFalse(
            PortfolioEngine._info_quote_is_newer(
                "2026-07-24", "2026-07-24", 204.89, 204.89
            )
        )


class FetchMarketQuotesTests(unittest.TestCase):
    @patch("engine.yf.download")
    def test_download_receives_impersonating_session(self, download) -> None:
        idx = pd.to_datetime(["2026-07-23", "2026-07-24"])
        frame = pd.DataFrame({"Close": [190.01, 204.89]}, index=idx)
        download.return_value = frame

        engine = PortfolioEngine()
        fake_session = object()
        with patch("services.market_cache.get_yf_session", return_value=fake_session), patch.object(
            engine, "_fetch_ticker_info", return_value={}
        ), patch(
            "services.company_name.resolve_company_name", return_value="HubSpot"
        ):
            quotes = engine.fetch_market_quotes(["HUBS"], include_analyst_targets=False)

        download.assert_called_once()
        kwargs = download.call_args.kwargs
        self.assertIs(kwargs.get("session"), fake_session)
        self.assertEqual(quotes["HUBS"]["currentPrice"], 204.89)
        self.assertEqual(quotes["HUBS"]["priceAsOf"], "2026-07-24")
        self.assertEqual(quotes["HUBS"]["dayChangePct"], 7.83)

    @patch("engine.yf.download", side_effect=RuntimeError("blocked"))
    def test_history_fallback_when_download_fails(self, _download) -> None:
        idx = pd.to_datetime(["2026-07-23", "2026-07-24"])
        hist = pd.DataFrame({"Close": [190.01, 204.89]}, index=idx)

        engine = PortfolioEngine()
        ticker = MagicMock()
        ticker.history.return_value = hist

        with patch("services.market_cache.get_yf_session", return_value=None), patch(
            "services.market_cache.reset_yf_session"
        ), patch(
            "services.market_cache.make_ticker", return_value=ticker
        ), patch(
            "services.market_cache.yf_pool.map", side_effect=lambda fn, items: [fn(x) for x in items]
        ), patch.object(
            engine, "_fetch_ticker_info", return_value={}
        ), patch(
            "services.company_name.resolve_company_name", return_value="HubSpot"
        ):
            quotes = engine.fetch_market_quotes(["HUBS"], include_analyst_targets=False)

        self.assertEqual(quotes["HUBS"]["currentPrice"], 204.89)
        self.assertEqual(quotes["HUBS"]["priceAsOf"], "2026-07-24")

    @patch("engine.yf.download")
    def test_info_fallback_when_history_missing(self, download) -> None:
        download.return_value = pd.DataFrame()
        ts = int(datetime(2026, 7, 24, 16, 0, tzinfo=ZoneInfo("America/New_York")).timestamp())
        info = {
            "regularMarketPrice": 204.89,
            "regularMarketChangePercent": 7.83,
            "regularMarketTime": ts,
        }

        engine = PortfolioEngine()
        with patch("services.market_cache.get_yf_session", return_value=None), patch(
            "services.market_cache.make_ticker"
        ) as make_ticker, patch.object(
            engine, "_fetch_ticker_info", return_value=info
        ), patch(
            "services.company_name.resolve_company_name", return_value="HubSpot"
        ):
            make_ticker.return_value.history.return_value = pd.DataFrame()
            with patch(
                "services.market_cache.yf_pool.map",
                side_effect=lambda fn, items: [fn(x) for x in items],
            ):
                quotes = engine.fetch_market_quotes(["HUBS"], include_analyst_targets=False)

        self.assertEqual(quotes["HUBS"]["currentPrice"], 204.89)
        self.assertEqual(quotes["HUBS"]["priceAsOf"], "2026-07-24")
        self.assertEqual(quotes["HUBS"]["dayChangePct"], 7.83)

    @patch("engine.yf.download")
    def test_prefers_newer_info_when_history_stuck_prior_session(self, download) -> None:
        """Render chart feed can end Thursday while quoteSummary has Friday close."""
        idx = pd.to_datetime(["2026-07-22", "2026-07-23"])
        frame = pd.DataFrame({"Close": [204.90, 190.01]}, index=idx)
        download.return_value = frame
        ts = int(datetime(2026, 7, 24, 16, 0, tzinfo=ZoneInfo("America/New_York")).timestamp())
        info = {
            "regularMarketPrice": 204.89,
            "previousClose": 190.01,
            "regularMarketChangePercent": 7.83,
            "regularMarketTime": ts,
        }

        engine = PortfolioEngine()
        with patch("services.market_cache.get_yf_session", return_value=object()), patch.object(
            engine, "_fetch_ticker_info", return_value=info
        ), patch(
            "services.company_name.resolve_company_name", return_value="HubSpot"
        ):
            quotes = engine.fetch_market_quotes(["HUBS"], include_analyst_targets=False)

        self.assertEqual(quotes["HUBS"]["currentPrice"], 204.89)
        self.assertEqual(quotes["HUBS"]["priceAsOf"], "2026-07-24")
        self.assertEqual(quotes["HUBS"]["dayChangePct"], 7.83)


class SyncQuotesAtomicityTests(unittest.TestCase):
    def test_day_change_without_price_is_not_persisted(self) -> None:
        """Regression: orphan day% must not rewrite while close stays stale."""
        from services.market_data_service import MarketDataService

        captured: dict = {}

        class _Engine:
            def fetch_market_quotes(self, tickers, include_analyst_targets=True):
                return {
                    "HUBS": {
                        "currentPrice": None,
                        "dayChangePct": 7.83,
                        "priceAsOf": "2026-07-24",
                        "analystTarget1y": None,
                        "analystTargetLow": None,
                        "analystTargetHigh": None,
                        "companyName": None,
                    }
                }

        class _Conn:
            def execute(self, sql, params=None):
                captured["params"] = params
                return self

            def commit(self):
                return None

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with patch("services.market_data_service.get_connection", return_value=_Conn()), patch(
            "services.market_data_service.resolve_company_name", return_value=None
        ):
            result = MarketDataService().sync_quotes(_Engine(), ["HUBS"], refresh_targets=False)

        # No usable quote fields → row write skipped
        self.assertEqual(result["updated"], 0)
        self.assertNotIn("params", captured)


if __name__ == "__main__":
    unittest.main()
