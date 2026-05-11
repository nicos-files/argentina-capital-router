import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.policies.topk_net_after_fees import apply_topk_net_after_fees


class ExecutionSemanticsTests(unittest.TestCase):
    def test_cash_clipping_sets_effective_weight(self) -> None:
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
        self.assertAlmostEqual(float(item.get("usd_target_effective") or 0.0), 59.0, places=6)
        self.assertAlmostEqual(float(item.get("cash_used_usd") or 0.0), 60.0, places=6)
        self.assertAlmostEqual(float(item.get("weight") or 0.0), 0.59, places=6)
        self.assertGreaterEqual(float(item.get("min_notional_usd") or 0.0), 50.0)

    def test_shared_cash_pool_prevents_double_spend_across_horizons(self) -> None:
        decisions = [
            {
                "asset_id": "AAPL",
                "signal": 1.0,
                "outputs": {"decision_type": "intraday", "model_score": 0.95},
            },
            {
                "asset_id": "MSFT",
                "signal": 1.0,
                "outputs": {"decision_type": "long_term", "model_score": 0.95},
            },
        ]
        recs = apply_topk_net_after_fees(
            decisions=decisions,
            asof_date=None,
            execution_date=None,
            execution_hour=None,
            price_map={"AAPL": 10.0, "MSFT": 10.0},
            positions={},
            cash_by_currency={"USD": 100.0},
            cash_by_broker=None,
        )
        intraday = next(r for r in recs if r.get("asset_id") == "AAPL" and r.get("horizon") == "INTRADAY")
        long_term = next(r for r in recs if r.get("asset_id") == "MSFT" and r.get("horizon") == "LONG_TERM")
        self.assertEqual(intraday.get("order_status"), "CLIPPED_CASH")
        self.assertAlmostEqual(float(intraday.get("cash_used_usd") or 0.0), 100.0, places=6)
        self.assertEqual(long_term.get("order_status"), "BLOCKED_CASH")
        self.assertAlmostEqual(float(long_term.get("cash_used_usd") or 0.0), 0.0, places=6)

    def test_fx_missing_blocks_non_usd(self) -> None:
        decisions = [
            {
                "asset_id": "GGAL.BA",
                "signal": 1.0,
                "outputs": {"decision_type": "intraday", "model_score": 0.9},
            }
        ]
        recs = apply_topk_net_after_fees(
            decisions=decisions,
            asof_date=None,
            execution_date=None,
            execution_hour=None,
            price_map={"GGAL.BA": 100.0},
            positions={},
            cash_by_currency={"ARS": 10000.0},
            cash_by_broker=None,
        )
        item = next(r for r in recs if r.get("asset_id") == "GGAL.BA" and r.get("horizon") == "INTRADAY")
        self.assertEqual(item.get("order_status"), "BLOCKED_FX")
        self.assertIn("fx_rate_missing", item.get("constraints", []))

    def test_intraday_only_decisions_do_not_generate_synthetic_long_term(self) -> None:
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
            cash_by_currency={"USD": 100.0},
            cash_by_broker=None,
        )
        long_term = [item for item in recs if item.get("horizon") == "LONG_TERM"]
        self.assertEqual(long_term, [])

    def test_non_viable_buy_without_position_is_skip_not_exit(self) -> None:
        decisions = [
            {
                "asset_id": "JPM",
                "signal": 1.0,
                "outputs": {
                    "decision_type": "intraday",
                    "model_score": 0.99,
                    "expected_return_gross_pct": 0.00886,
                    "justificacion": "model_score=0.99",
                },
            }
        ]
        recs = apply_topk_net_after_fees(
            decisions=decisions,
            asof_date="2026-04-21",
            execution_date="2026-04-22",
            execution_hour="1940",
            price_map={"JPM": 312.47},
            positions={},
            cash_by_currency={"USD": 100.0},
            cash_by_broker=None,
        )
        item = next(r for r in recs if r.get("asset_id") == "JPM" and r.get("horizon") == "INTRADAY")
        self.assertEqual(item.get("action"), "SKIP")
        reason = item.get("reason") or ""
        self.assertTrue(
            "min_capital_viable_usd=" in reason or "broker_cost_floor>edge" in reason
        )


if __name__ == "__main__":
    unittest.main()
