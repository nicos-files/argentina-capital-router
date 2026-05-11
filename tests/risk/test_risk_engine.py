import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.risk import RiskCheckInput, RiskEngine


class RiskEngineTests(unittest.TestCase):
    def test_approve_when_no_limits_are_violated(self) -> None:
        engine = RiskEngine()
        result = engine.evaluate(
            RiskCheckInput(symbol="AAPL", side="BUY", notional=100.0, cash_available=150.0, fees_estimate=1.0)
        )
        self.assertTrue(result.approved)
        self.assertIn("approved", result.risk_tags)

    def test_reject_when_provider_unhealthy(self) -> None:
        engine = RiskEngine()
        result = engine.evaluate(RiskCheckInput(symbol="AAPL", side="BUY", provider_healthy=False))
        self.assertFalse(result.approved)
        self.assertEqual(result.rejected_reason, "provider_unhealthy")

    def test_approve_when_provider_unhealthy_but_check_disabled(self) -> None:
        engine = RiskEngine({"reject_if_provider_unhealthy": False})
        result = engine.evaluate(RiskCheckInput(symbol="AAPL", side="BUY", provider_healthy=False))
        self.assertTrue(result.approved)

    def test_reject_when_data_quality_below_min(self) -> None:
        engine = RiskEngine({"min_data_quality_score": 0.8})
        result = engine.evaluate(RiskCheckInput(symbol="AAPL", side="BUY", data_quality_score=0.7))
        self.assertFalse(result.approved)
        self.assertEqual(result.rejected_reason, "data_quality_below_min")

    def test_approve_when_data_quality_missing_and_minimum_none(self) -> None:
        engine = RiskEngine()
        result = engine.evaluate(RiskCheckInput(symbol="AAPL", side="BUY"))
        self.assertTrue(result.approved)

    def test_reject_when_expected_net_edge_below_min(self) -> None:
        engine = RiskEngine({"min_expected_net_edge": 0.01})
        result = engine.evaluate(RiskCheckInput(symbol="AAPL", side="BUY", expected_net_edge=0.005))
        self.assertFalse(result.approved)
        self.assertEqual(result.rejected_reason, "expected_net_edge_below_min")

    def test_reject_when_cash_available_is_insufficient(self) -> None:
        engine = RiskEngine()
        result = engine.evaluate(
            RiskCheckInput(symbol="AAPL", side="BUY", notional=100.0, cash_available=100.0, fees_estimate=1.0)
        )
        self.assertFalse(result.approved)
        self.assertEqual(result.rejected_reason, "cash_insufficient")

    def test_reject_when_notional_below_min(self) -> None:
        engine = RiskEngine({"min_notional": 50.0})
        result = engine.evaluate(RiskCheckInput(symbol="AAPL", side="BUY", notional=49.0))
        self.assertFalse(result.approved)
        self.assertEqual(result.rejected_reason, "notional_below_min")

    def test_reject_when_notional_above_max(self) -> None:
        engine = RiskEngine({"max_notional": 100.0})
        result = engine.evaluate(RiskCheckInput(symbol="AAPL", side="BUY", notional=101.0))
        self.assertFalse(result.approved)
        self.assertEqual(result.rejected_reason, "notional_above_max")

    def test_reject_when_spread_above_max(self) -> None:
        engine = RiskEngine({"max_spread_pct": 0.01})
        result = engine.evaluate(RiskCheckInput(symbol="AAPL", side="BUY", spread_pct=0.02))
        self.assertFalse(result.approved)
        self.assertEqual(result.rejected_reason, "spread_above_max")

    def test_reject_returns_useful_reason_and_tags(self) -> None:
        engine = RiskEngine({"min_expected_net_edge": 0.02})
        result = engine.evaluate(RiskCheckInput(symbol="AAPL", side="BUY", expected_net_edge=0.01))
        self.assertEqual(result.rejected_reason, "expected_net_edge_below_min")
        self.assertIn("expected_net_edge", result.risk_tags)
        self.assertIn("rejected", result.risk_tags)

    def test_missing_optional_fields_do_not_raise(self) -> None:
        engine = RiskEngine()
        result = engine.evaluate(RiskCheckInput(symbol="AAPL", side="BUY"))
        self.assertTrue(result.approved)


if __name__ == "__main__":
    unittest.main()
