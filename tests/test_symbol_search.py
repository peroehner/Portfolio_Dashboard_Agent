"""Unit tests for Finnhub ticker search / autocomplete."""
import unittest
from unittest.mock import MagicMock, patch

from services.symbol_search_service import search_tickers


class SymbolSearchTests(unittest.TestCase):
    def test_empty_query(self):
        out = search_tickers("  ")
        self.assertEqual(out["results"], [])
        self.assertFalse(out["providerUnavailable"])

    def test_missing_api_key(self):
        with patch.dict("os.environ", {"FINNHUB_API_KEY": ""}, clear=False):
            out = search_tickers("schaef")
        self.assertEqual(out["results"], [])
        self.assertTrue(out["providerUnavailable"])

    @patch("services.symbol_search_service.urllib.request.urlopen")
    def test_maps_finnhub_hits(self, urlopen):
        payload = {
            "count": 2,
            "result": [
                {
                    "description": "Schaeffler AG",
                    "displaySymbol": "SCHAEFFLER.NS",
                    "symbol": "SCHAEFFLER.NS",
                    "type": "Common Stock",
                },
                {
                    "description": "Schaeffler AG N",
                    "displaySymbol": "SHA0.F",
                    "symbol": "SHA0.F",
                    "type": "Common Stock",
                },
                {"description": "dup", "symbol": "SCHAEFFLER.NS", "type": "Common Stock"},
            ],
        }
        resp = MagicMock()
        resp.read.return_value = __import__("json").dumps(payload).encode()
        resp.__enter__.return_value = resp
        resp.__exit__.return_value = False
        urlopen.return_value = resp

        with patch.dict("os.environ", {"FINNHUB_API_KEY": "test-key"}):
            out = search_tickers("schaef", limit=10)

        self.assertFalse(out["providerUnavailable"])
        self.assertEqual(len(out["results"]), 2)
        self.assertEqual(out["results"][0]["symbol"], "SCHAEFFLER.NS")
        self.assertEqual(out["results"][0]["description"], "Schaeffler AG")
        self.assertEqual(out["results"][1]["symbol"], "SHA0.F")

    @patch("services.symbol_search_service.urllib.request.urlopen")
    def test_respects_limit(self, urlopen):
        payload = {
            "result": [
                {"symbol": f"T{i}", "description": f"Name {i}", "type": "Equity"}
                for i in range(20)
            ]
        }
        resp = MagicMock()
        resp.read.return_value = __import__("json").dumps(payload).encode()
        resp.__enter__.return_value = resp
        resp.__exit__.return_value = False
        urlopen.return_value = resp

        with patch.dict("os.environ", {"FINNHUB_API_KEY": "test-key"}):
            out = search_tickers("t", limit=5)

        self.assertEqual(len(out["results"]), 5)


if __name__ == "__main__":
    unittest.main()
