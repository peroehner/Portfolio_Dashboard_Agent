import os
import unittest
import unittest.mock

import psycopg

# These tests DROP SCHEMA on the target database, so they must never run against
# the dev/production DB. They only run when TEST_DATABASE_URL is explicitly set
# to a throwaway database; otherwise the DB-backed tests are skipped. Pointing
# the app at the test DB here ensures the pool and services use it too.
TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
if TEST_DATABASE_URL:
    os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from db.database import (  # noqa: E402 - import after DATABASE_URL override
    close_pool,
    get_database_url,
    init_db,
    reset_bootstrap_user_cache,
)
from services.import_service import ImportService  # noqa: E402
from services.inspector_service import InspectorService  # noqa: E402
from services.technical_service import TechnicalService  # noqa: E402


def _db_available() -> bool:
    if not TEST_DATABASE_URL:
        return False
    try:
        with psycopg.connect(TEST_DATABASE_URL, connect_timeout=3):
            return True
    except Exception:
        return False


DB_AVAILABLE = _db_available()


def _reset_schema() -> None:
    """Drop and recreate the public schema for an isolated test database."""
    close_pool()
    with psycopg.connect(get_database_url(), autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    reset_bootstrap_user_cache()
    init_db()


SAMPLE_EXPORT = """
[TECHNICAL ANALYSIS EXPORT: TSLA]
Generated: 2026-06-10 12:00:00
Fibonacci anchor: T1 Bullish: 2026-04-21 → 2026-05-12
Current Price: 380.00 $

Time window: 2026-04 → 2026-06
Detected Trends:
- T1 (Bullish): 2026-04-21 330.27 $ to 2026-05-12 383.59 $ (Move: 16.1%)
- T2 (Bullish): 2026-04-02 294.28 $ to 2026-04-21 330.27 $ (Move: 12.2%)
- T3 (Bearish): 2026-05-28 385.89 $ to 2026-06-03 355.47 $ (Move: 7.9%)
Fibonacci Levels:
- 0% (High): 398.13 $
- 38.2% Retracement: 371.89 $
- 50.0% Center Line: 363.78 $
- 61.8% Golden Pocket: 355.67 $
- 100% (Low Base): 329.43 $
"""


class TechnicalImportTestCase(unittest.TestCase):
    def setUp(self):
        if DB_AVAILABLE:
            _reset_schema()
        self.import_service = ImportService()
        self.technical_service = TechnicalService()

    def test_fib_label_styles_do_not_collide(self):
        self.assertEqual(
            self.technical_service.style_for_fib_label("0% (High)")["shortLabel"],
            "0% High",
        )
        self.assertEqual(
            self.technical_service.style_for_fib_label("50.0% Center Line")["shortLabel"],
            "50.0% Center",
        )
        self.assertEqual(
            self.technical_service.style_for_fib_label("100% (Low Base)")["shortLabel"],
            "100% Base",
        )

    def test_parse_export_body(self):
        snapshot = self.technical_service.parse_export_body(SAMPLE_EXPORT)
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot["windowStart"], "2026-04")
        self.assertEqual(snapshot["windowEnd"], "2026-06")
        self.assertEqual(len(snapshot["trends"]), 3)
        self.assertEqual(snapshot["trends"][0]["label"], "T1")
        self.assertEqual(snapshot["trends"][0]["priceStart"], 330.27)
        self.assertEqual(snapshot["trends"][0]["movePct"], 16.1)
        self.assertEqual(snapshot["trends"][2]["type"], "Bearish")
        self.assertIn("0% (High)", snapshot["fibLevels"])
        self.assertEqual(snapshot["fibLevels"]["0% (High)"], 398.13)

    @unittest.skipUnless(DB_AVAILABLE, "Set TEST_DATABASE_URL to a throwaway DB to run schema tests")
    def test_import_txt_persists_technical_snapshot(self):
        result = self.import_service.import_txt(SAMPLE_EXPORT, mode="merge")
        self.assertEqual(result["symbolsImported"], 1)
        snapshot = self.technical_service.get_snapshot("TSLA")
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(len(snapshot["trends"]), 3)
        self.assertAlmostEqual(snapshot["fibLevels"]["50.0% Center Line"], 363.78)

    @unittest.skipUnless(DB_AVAILABLE, "Set TEST_DATABASE_URL to a throwaway DB to run schema tests")
    def test_inspector_uses_imported_fib_anchor(self):
        self.import_service.import_txt(SAMPLE_EXPORT, mode="merge")
        inspector = InspectorService()
        with unittest.mock.patch("services.inspector_service.yf.Ticker") as ticker_mock:
            ticker_mock.return_value.info = {}
            data = inspector.inspect("TSLA")
        self.assertIsNotNone(data)
        assert data is not None
        self.assertEqual(data["trendWaveSource"], "import")
        self.assertEqual(len(data["trendWaves"]), 3)
        self.assertEqual(
            [wave["label"] for wave in data["trendWaves"]],
            ["T2", "T1", "T3"],
        )
        t1 = next(wave for wave in data["trendWaves"] if wave["label"] == "T1")
        self.assertEqual(t1["legPattern"], "Low → Peak (Bullish)")
        self.assertIn("From 2026-04-21 until 2026-05-12", t1["legSummary"])
        self.assertEqual(t1["peakHigh"], 398.13)
        self.assertEqual(t1["peakLow"], 329.43)
        self.assertEqual(data["fib"]["swingHigh"], 398.13)
        self.assertEqual(len(data["importedFibLevels"]), 5)


if __name__ == "__main__":
    unittest.main()
