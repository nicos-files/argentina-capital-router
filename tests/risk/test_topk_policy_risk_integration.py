import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.policies.topk_net_after_fees import apply_topk_net_after_fees
from src.risk import RiskEngine


class TopkPolicyRiskIntegrationTests(unittest.TestCase):
    def test_neutral_risk_engine_preserves_existing_behavior(self) -> None:
        decisions = [
            {
                "asset_id": "AAPL",
                "signal": 1.0,
                "outputs": {"decision_type": "intraday", "model_score": 0.9},
            }
        ]

        recs = apply_topk_net_after_fees(
            decisions=decisions,
            asof_date=None,
            execution_date=None,
            execution_hour=None,
            price_map={"AAPL": 10.0},
            positions={},
            cash_by_currency={"USD": 60.0},
            cash_by_broker=None,
        )
        item = next(r for r in recs if r.get("asset_id") == "AAPL" and r.get("horizon") == "INTRADAY")
        self.assertEqual(item.get("order_status"), "CLIPPED_CASH")
        self.assertEqual(item.get("order_side"), "BUY")

    def test_risk_engine_can_reject_without_breaking_output_shape(self) -> None:
        decisions = [
            {
                "asset_id": "AAPL",
                "signal": 1.0,
                "outputs": {
                    "decision_type": "intraday",
                    "model_score": 0.95,
                    "expected_return_gross_pct": 0.20,
                    "justificacion": "model_score=0.95",
                },
            }
        ]

        with patch(
            "src.decision_intel.policies.topk_net_after_fees._build_risk_engine",
            return_value=RiskEngine({"min_expected_net_edge": 0.50}),
        ):
            recs = apply_topk_net_after_fees(
                decisions=decisions,
                asof_date="2026-04-21",
                execution_date="2026-04-22",
                execution_hour="1000",
                price_map={"AAPL": 10.0},
                positions={},
                cash_by_currency={"USD": 1000.0},
                cash_by_broker=None,
            )

        item = next(r for r in recs if r.get("asset_id") == "AAPL" and r.get("horizon") == "INTRADAY")
        self.assertEqual(item.get("action"), "SKIP")
        self.assertEqual(item.get("order_status"), "BLOCKED_RISK")
        self.assertIn("risk_rejected", item.get("constraints", []))
        self.assertIn("risk:expected_net_edge_below_min", item.get("reason") or "")


if __name__ == "__main__":
    unittest.main()
