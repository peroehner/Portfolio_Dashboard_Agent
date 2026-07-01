"""Unit tests for the alert staleness decision logic.

These exercise the pure, DB-free pieces of ``AlertsService``: the signature
normalization and the ``active``↔``stale`` transition classifier. The DB-bound
parts (``_apply_staleness``/``evaluate_all``) are integration concerns that need
a throwaway Postgres and are covered by the schema-tests path.
"""

import unittest

from services.alerts_service import AlertsService


def _row(id_, symbol, alert_type, reference_value, status, fib_level=None):
    return {
        "id": id_,
        "symbol": symbol,
        "alert_type": alert_type,
        "reference_value": reference_value,
        "fib_level": fib_level,
        "status": status,
    }


class SignatureTests(unittest.TestCase):
    def test_normalizes_symbol_and_nulls(self):
        sig = AlertsService._signature("aapl", "trade_below", None, None)
        self.assertEqual(sig, ("AAPL", "trade_below", -1.0, ""))

    def test_reference_rounding_is_tolerant(self):
        # A value round-tripped through Postgres can drift in the low digits;
        # both should produce the same signature.
        a = AlertsService._signature("MSFT", "trade_above", 123.45001, None)
        b = AlertsService._signature("MSFT", "trade_above", 123.45, None)
        self.assertEqual(a, b)

    def test_fib_level_is_part_of_identity(self):
        a = AlertsService._signature("NVDA", "fib_proximity", 100.0, "0.618")
        b = AlertsService._signature("NVDA", "fib_proximity", 100.0, "0.5")
        self.assertNotEqual(a, b)


class StalenessTransitionTests(unittest.TestCase):
    def test_active_no_longer_true_becomes_stale(self):
        rows = [_row(1, "AAPL", "trade_below", 150.0, "active")]
        changes = AlertsService._staleness_transitions(rows, set())
        self.assertEqual(changes, {1: "stale"})

    def test_active_still_true_unchanged(self):
        rows = [_row(1, "AAPL", "trade_below", 150.0, "active")]
        true_sigs = {AlertsService._signature("AAPL", "trade_below", 150.0, None)}
        changes = AlertsService._staleness_transitions(rows, true_sigs)
        self.assertEqual(changes, {})

    def test_stale_true_again_is_superseded(self):
        # Revival = supersede-and-recreate: a fresh active row is created in the
        # check phase, so the old stale row is retired (superseded), not revived
        # in place.
        rows = [_row(7, "TSLA", "trade_above", 300.0, "stale")]
        true_sigs = {AlertsService._signature("TSLA", "trade_above", 300.0, None)}
        changes = AlertsService._staleness_transitions(rows, true_sigs)
        self.assertEqual(changes, {7: "superseded"})

    def test_stale_still_false_unchanged(self):
        rows = [_row(7, "TSLA", "trade_above", 300.0, "stale")]
        changes = AlertsService._staleness_transitions(rows, set())
        self.assertEqual(changes, {})

    def test_mixed_batch(self):
        rows = [
            _row(1, "AAPL", "trade_below", 150.0, "active"),   # true -> keep
            _row(2, "AAPL", "trade_below_near", 150.0, "active"),  # not true -> stale
            _row(3, "MSFT", "fib_proximity", 410.0, "stale", fib_level="0.618"),  # true -> superseded
            _row(4, "NVDA", "screener_upside", None, "stale"),  # not true -> keep
        ]
        true_sigs = {
            AlertsService._signature("AAPL", "trade_below", 150.0, None),
            AlertsService._signature("MSFT", "fib_proximity", 410.0, "0.618"),
        }
        changes = AlertsService._staleness_transitions(rows, true_sigs)
        self.assertEqual(changes, {2: "stale", 3: "superseded"})


if __name__ == "__main__":
    unittest.main()
