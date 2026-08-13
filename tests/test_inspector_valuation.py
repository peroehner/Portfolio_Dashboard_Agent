import unittest

from services.inspector_service import InspectorService


class InspectorValuationFractionsTest(unittest.TestCase):
    def test_growth_metrics_store_yfinance_fractions(self):
        # yfinance revenueGrowth=6.839 means +683.9% YoY, not +6.839%.
        self.assertEqual(InspectorService._safe_round(6.839, digits=4), 6.839)
        self.assertEqual(InspectorService._safe_round(0.166, digits=4), 0.166)
        self.assertEqual(InspectorService._safe_round(-0.32, digits=4), -0.32)


if __name__ == "__main__":
    unittest.main()
