import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.execution.plan_writer import write_execution_plan


class ExecutionPlanWriterTests(unittest.TestCase):
    def test_execution_plan_filters_executable_orders(self) -> None:
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            run_id = "20260101-0930"
            run_root = base / "runs" / run_id / "artifacts"
            run_root.mkdir(parents=True, exist_ok=True)
            rec_path = run_root / "recommendation.outputs.v1.0.0.json"
            rec_payload = {
                "schema_version": "1.0.0",
                "reader_min_version": "1.0.0",
                "run_id": run_id,
                "asof_date": "2026-01-01",
                "execution_date": "2026-01-02",
                "execution_hour": "0930",
                "policy_id": "policy.topk.net_after_fees.v1",
                "policy_version": "1",
                "recommendations": [
                    {
                        "ticker": "AAPL",
                        "asset_id": "AAPL",
                        "horizon": "INTRADAY",
                        "broker_selected": "generic_us",
                        "order_side": "BUY",
                        "order_type": "MARKET",
                        "time_in_force": "DAY",
                        "order_qty": 5.0,
                        "order_notional_usd": 50.0,
                        "order_notional_ccy": 50.0,
                        "currency": "USD",
                        "fx_rate_used": 1.0,
                        "fx_rate_source": "native_usd",
                        "price_used": 10.0,
                        "price_source": "features.close",
                        "min_notional_usd": 1.0,
                        "order_status": "READY",
                        "fees_estimated_usd": 1.0,
                        "current_qty": 0.0,
                        "qty_target": 5.0,
                        "delta_qty": 5.0,
                    },
                    {
                        "ticker": "GGAL.BA",
                        "asset_id": "GGAL.BA",
                        "horizon": "INTRADAY",
                        "order_side": "BUY",
                        "order_qty": 10.0,
                        "order_status": "BLOCKED_FX",
                    },
                ],
            }
            rec_path.write_text(json.dumps(rec_payload), encoding="utf-8")

            plan_path, _entry = write_execution_plan(
                run_id=run_id,
                recommendations_path=rec_path,
                base_path=str(base / "runs"),
            )
            plan_payload = json.loads(plan_path.read_text(encoding="utf-8"))
            orders = plan_payload.get("orders", [])
            self.assertEqual(len(orders), 1)
            self.assertEqual(orders[0]["asset_id"], "AAPL")


if __name__ == "__main__":
    unittest.main()
