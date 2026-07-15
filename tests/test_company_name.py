import unittest
from unittest.mock import patch

from services.company_name import (
    company_name_from_finnhub,
    company_name_from_info,
    resolve_company_name,
)


class CompanyNameTests(unittest.TestCase):
    def test_company_name_from_info_prefers_long_name(self) -> None:
        info = {"longName": "Apple Inc.", "shortName": "Apple"}
        self.assertEqual(company_name_from_info(info), "Apple Inc.")

    def test_company_name_from_info_short_name_fallback(self) -> None:
        self.assertEqual(company_name_from_info({"shortName": "Apple"}), "Apple")

    @patch("services.company_name.urllib.request.urlopen")
    def test_resolve_company_name_uses_finnhub_when_info_missing(self, urlopen) -> None:
        company_name_from_finnhub.cache_clear() if hasattr(company_name_from_finnhub, "cache_clear") else None
        import services.company_name as mod

        mod._finnhub_name_cache.clear()
        with patch.dict("os.environ", {"FINNHUB_API_KEY": "test-key"}):
            urlopen.return_value.__enter__.return_value.read.return_value = b'{"name":"Apple Inc"}'
            self.assertEqual(resolve_company_name("AAPL", {}), "Apple Inc")

    @patch("services.company_name.company_name_from_finnhub", return_value="Amazon.com, Inc.")
    def test_resolve_company_name_skips_finnhub_when_info_has_name(self, finnhub) -> None:
        self.assertEqual(
            resolve_company_name("AMZN", {"longName": "Amazon.com, Inc."}),
            "Amazon.com, Inc.",
        )
        finnhub.assert_not_called()


if __name__ == "__main__":
    unittest.main()
