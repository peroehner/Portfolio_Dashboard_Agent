"""News fetch must fail fast and not chain Finnhub timeouts into Yahoo."""

import unittest
from unittest.mock import patch
from urllib.error import URLError

from services import fundamentals_service as fs
from services.fundamentals_service import FundamentalsService, _is_timeout_error


class TimeoutClassifierTests(unittest.TestCase):
    def test_handshake_timeout(self):
        exc = URLError("_ssl.c:1063: The handshake operation timed out")
        self.assertTrue(_is_timeout_error(exc))

    def test_curl_28(self):
        self.assertTrue(_is_timeout_error(RuntimeError("curl: (28) Connection timed out after 30001 milliseconds")))

    def test_http_429_is_not_timeout(self):
        self.assertFalse(_is_timeout_error(RuntimeError("HTTP Error 429: Too Many Requests")))


class NewsFetchFailFastTests(unittest.TestCase):
    def setUp(self):
        fs._news_timeout_until[0] = 0.0
        fs._finnhub_429_until[0] = 0.0
        fs.news_cache.clear()
        fs.yf_failure_cache.clear()
        self.svc = FundamentalsService()
        self.svc.news_limit = 6
        self.svc.finnhub_api_key = "test-key"
        self.svc.news_provider = "finnhub"

    def tearDown(self):
        fs._news_timeout_until[0] = 0.0
        fs._finnhub_429_until[0] = 0.0
        fs.news_cache.clear()
        fs.yf_failure_cache.clear()

    @patch.object(FundamentalsService, "_fetch_yfinance_news")
    @patch.object(FundamentalsService, "_fetch_finnhub_news")
    def test_timeout_skips_yfinance_fallback(self, finnhub, yfinance):
        finnhub.side_effect = URLError("_ssl.c:1063: The handshake operation timed out")
        news = self.svc.fetch_recent_news("TTD")
        self.assertEqual(news, [])
        yfinance.assert_not_called()
        self.assertTrue(fs._news_timeout_cooling())

    @patch.object(FundamentalsService, "_fetch_yfinance_news")
    @patch.object(FundamentalsService, "_fetch_finnhub_news")
    def test_timeout_cooldown_skips_next_symbol(self, finnhub, yfinance):
        finnhub.side_effect = TimeoutError("timed out")
        self.svc.fetch_recent_news("VISN")
        finnhub.reset_mock()
        news = self.svc.fetch_recent_news("SIE.DE")
        self.assertEqual(news, [])
        finnhub.assert_not_called()
        yfinance.assert_not_called()

    @patch.object(FundamentalsService, "_fetch_yfinance_news")
    @patch.object(FundamentalsService, "_fetch_finnhub_news")
    def test_http_403_skips_yfinance_fallback(self, finnhub, yfinance):
        err = URLError("HTTP Error 403: Forbidden")
        err.code = 403
        finnhub.side_effect = err
        news = self.svc.fetch_recent_news("OBH.F")
        self.assertEqual(news, [])
        yfinance.assert_not_called()

    @patch.object(FundamentalsService, "_fetch_yfinance_news", return_value=[{"title": "ok"}])
    @patch.object(FundamentalsService, "_fetch_finnhub_news")
    def test_http_429_still_falls_back(self, finnhub, yfinance):
        err = URLError("HTTP Error 429")
        err.code = 429
        finnhub.side_effect = err
        news = self.svc.fetch_recent_news("AAPL")
        self.assertEqual(news, [{"title": "ok"}])
        yfinance.assert_called_once()
