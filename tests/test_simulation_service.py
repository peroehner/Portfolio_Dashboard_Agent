"""Criteria normalization for saved simulation snapshots."""
import unittest

from services.simulation_service import _as_bool, _as_filter, _as_legs, _as_symbol_list


class SimulationCriteriaHelpersTest(unittest.TestCase):
    def test_filter_values(self):
        self.assertEqual(_as_filter("close"), "close")
        self.assertEqual(_as_filter("FAR"), "far")
        self.assertEqual(_as_filter("invalid"), "all")
        self.assertEqual(_as_filter(None), "all")

    def test_legs_values(self):
        self.assertEqual(_as_legs("buys"), "buys")
        self.assertEqual(_as_legs("SELLS"), "sells")
        self.assertEqual(_as_legs("nope"), "both")

    def test_symbol_list(self):
        self.assertEqual(_as_symbol_list(["aapl", " msft "]), ["AAPL", "MSFT"])
        self.assertEqual(_as_symbol_list("bad"), [])

    def test_bool(self):
        self.assertTrue(_as_bool(True))
        self.assertTrue(_as_bool("yes"))
        self.assertFalse(_as_bool("no"))
        self.assertFalse(_as_bool(0))


if __name__ == "__main__":
    unittest.main()
