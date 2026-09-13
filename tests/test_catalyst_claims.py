"""Unit tests for catalyst claim helpers (no DB required)."""

import importlib.util
import sys
import types
import unittest
from pathlib import Path


def _load_catalyst_module():
    """Load catalyst_claims_service without importing services package __init__."""
    path = Path(__file__).resolve().parents[1] / "services" / "catalyst_claims_service.py"
    if "db.database" not in sys.modules:
        db_mod = types.ModuleType("db.database")
        db_mod.get_connection = lambda: None  # type: ignore[attr-defined]
        db_mod.get_current_user_id = lambda: 1  # type: ignore[attr-defined]
        sys.modules.setdefault("db", types.ModuleType("db"))
        sys.modules["db.database"] = db_mod
    spec = importlib.util.spec_from_file_location("catalyst_claims_service_under_test", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_mod = _load_catalyst_module()
CatalystClaimsService = _mod.CatalystClaimsService


class CatalystClaimsHelpersTests(unittest.TestCase):
    def test_infer_metric_key_aliases(self) -> None:
        self.assertEqual(
            CatalystClaimsService.infer_metric_key("Security revenue growth YoY"),
            "revenueGrowth",
        )
        self.assertEqual(
            CatalystClaimsService.infer_metric_key("EBITDA margin expansion"),
            "ebitdaMargin",
        )
        self.assertEqual(CatalystClaimsService.infer_metric_key("ARR run-rate"), "arr")
        self.assertIsNone(CatalystClaimsService.infer_metric_key("customer NPS"))

    def test_parse_threshold(self) -> None:
        parsed = CatalystClaimsService._parse_threshold(">= 25%+")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["value"], 25.0)
        self.assertEqual(parsed["unit"], "%")

        parsed_bps = CatalystClaimsService._parse_threshold("up 120 bps")
        self.assertIsNotNone(parsed_bps)
        assert parsed_bps is not None
        self.assertEqual(parsed_bps["value"], 120.0)
        self.assertEqual(parsed_bps["unit"], "bps")

    def test_infer_direction(self) -> None:
        self.assertEqual(CatalystClaimsService._infer_direction("below 40%"), "below")
        self.assertEqual(CatalystClaimsService._infer_direction("25%+"), "above")
        self.assertEqual(CatalystClaimsService._infer_direction("at least 30%"), "above")

    def test_compare_status_above(self) -> None:
        self.assertEqual(
            CatalystClaimsService._compare_status(31.0, 25.0, "above"),
            "substantiated",
        )
        self.assertEqual(
            CatalystClaimsService._compare_status(10.0, 25.0, "above"),
            "missed",
        )
        self.assertEqual(
            CatalystClaimsService._compare_status(24.0, 25.0, "above"),
            "inconclusive",
        )

    def test_compare_status_below(self) -> None:
        self.assertEqual(
            CatalystClaimsService._compare_status(35.0, 40.0, "below"),
            "substantiated",
        )
        self.assertEqual(
            CatalystClaimsService._compare_status(55.0, 40.0, "below"),
            "missed",
        )

    def test_claim_key_stable(self) -> None:
        a = CatalystClaimsService._claim_key(
            {"period": "Q2 2026", "metric": "Security YoY", "threshold": "25%+"}
        )
        b = CatalystClaimsService._claim_key(
            {"period": "Q2  2026", "metric": "Security YoY", "threshold": "25%+"}
        )
        self.assertEqual(a, b)
        self.assertEqual(len(a), 24)

    def test_normalize_catalyst_fills_metric_key(self) -> None:
        svc = CatalystClaimsService()
        out = svc._normalize_catalyst(
            {
                "period": "Q2 2026",
                "metric": "Revenue growth",
                "threshold": "20%+",
                "significance": "Core thesis check",
            }
        )
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(out["metricKey"], "revenueGrowth")
        self.assertEqual(out["direction"], "above")

    def test_auto_verdict_skips_same_note_evidence(self) -> None:
        svc = CatalystClaimsService()
        claim = {
            "id": 1,
            "noteId": 10,
            "period": "Q2 2026",
            "metric": "Revenue growth",
            "metricKey": "revenueGrowth",
            "threshold": "25%+",
            "direction": "above",
        }
        evidence = {
            "fundamentals": {},
            "observations": [
                {
                    "metric": "Revenue growth",
                    "metricKey": "revenueGrowth",
                    "valueText": "31% YoY",
                    "period": "Q2 2026",
                    "noteId": 10,
                }
            ],
            "hasSignal": True,
        }
        self.assertIsNone(svc._auto_verdict(claim, evidence))

    def test_auto_verdict_from_later_note(self) -> None:
        svc = CatalystClaimsService()
        claim = {
            "id": 1,
            "noteId": 10,
            "period": "Q2 2026",
            "metric": "Revenue growth",
            "metricKey": "revenueGrowth",
            "threshold": "25%+",
            "direction": "above",
        }
        evidence = {
            "fundamentals": {},
            "observations": [
                {
                    "metric": "Revenue growth",
                    "metricKey": "revenueGrowth",
                    "valueText": "31% YoY",
                    "period": "Q2 2026",
                    "noteId": 11,
                }
            ],
            "hasSignal": True,
        }
        verdict = svc._auto_verdict(claim, evidence)
        self.assertIsNotNone(verdict)
        assert verdict is not None
        self.assertEqual(verdict["status"], "substantiated")
        self.assertEqual(verdict["evidenceNoteId"], 11)

    def test_auto_verdict_from_fundamentals(self) -> None:
        svc = CatalystClaimsService()
        claim = {
            "id": 2,
            "noteId": 1,
            "period": "TTM",
            "metric": "Operating margin",
            "metricKey": "operatingMargin",
            "threshold": "15%+",
            "direction": "above",
        }
        evidence = {
            "fundamentals": {"operatingMargin": 0.18},
            "observations": [],
            "hasSignal": True,
        }
        verdict = svc._auto_verdict(claim, evidence)
        self.assertIsNotNone(verdict)
        assert verdict is not None
        self.assertEqual(verdict["status"], "substantiated")
        self.assertIn("18.0%", verdict["observedValue"])


if __name__ == "__main__":
    unittest.main()
