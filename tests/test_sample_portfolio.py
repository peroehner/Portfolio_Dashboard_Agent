import json
import unittest
from pathlib import Path

from db.database import init_db, reset_bootstrap_user_cache, set_current_user_id
from services.import_service import ImportService
from services.portfolio_service import PortfolioService

SAMPLE_PATH = Path(__file__).resolve().parents[1] / "data" / "Sample-Portfolio.json"


class SamplePortfolioTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()
        reset_bootstrap_user_cache()

    def setUp(self) -> None:
        set_current_user_id(None)
        PortfolioService().clear_portfolio()

    def test_sample_portfolio_file_exists(self) -> None:
        self.assertTrue(SAMPLE_PATH.is_file(), "data/Sample-Portfolio.json is missing")

    def test_sample_portfolio_imports_six_symbols(self) -> None:
        payload = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
        positions = payload.get("positions") or []
        self.assertEqual(len(positions), 6)

        result = ImportService().import_payload(payload, mode="merge")
        self.assertEqual(result["symbolsImported"], 6)
        symbols = {item["symbol"] for item in result["symbols"]}
        self.assertEqual(
            symbols,
            {"AAPL", "CRWD", "GOOG", "IBRX", "PLTR", "SAP"},
        )

    def test_sample_portfolio_has_watch_only_symbol(self) -> None:
        payload = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
        crwd = next(item for item in payload["positions"] if item["symbol"] == "CRWD")
        self.assertIsNone(crwd.get("shares"))


if __name__ == "__main__":
    unittest.main()
