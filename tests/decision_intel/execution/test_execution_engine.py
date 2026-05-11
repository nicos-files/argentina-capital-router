import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.execution.execution_engine import execute_plan


class ExecutionEngineTests(unittest.TestCase):
    def test_paper_execution_updates_positions_and_is_idempotent(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_id = "20260101-0930"
            plan_path = root / "runs" / run_id / "artifacts" / "execution.plan.v1.0.0.json"
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_payload = {
                "schema_version": "1.0.0",
                "reader_min_version": "1.0.0",
                "run_id": run_id,
                "asof_date": "2026-01-01",
                "execution_date": "2026-01-02",
                "execution_hour": "0930",
                "orders": [
                    {
                        "order_id": "a-sell",
                        "asset_id": "AAA",
                        "ticker": "AAA",
                        "broker_selected": "iol",
                        "order_side": "SELL",
                        "order_status": "READY",
                        "order_qty": 2.0,
                        "price_used": 10.0,
                        "currency": "USD",
                        "fees_estimated_usd": 1.0,
                    },
                    {
                        "order_id": "b-buy",
                        "asset_id": "BBB",
                        "ticker": "BBB",
                        "broker_selected": "iol",
                        "order_side": "BUY",
                        "order_status": "READY",
                        "order_qty": 1.0,
                        "price_used": 5.0,
                        "currency": "USD",
                        "fees_estimated_usd": 1.0,
                    },
                ],
            }
            plan_path.write_text(json.dumps(plan_payload), encoding="utf-8")

            positions_path = root / "data" / "results" / "positions.json"
            positions_path.parent.mkdir(parents=True, exist_ok=True)
            positions_payload = {
                "positions": [
                    {"asset_id": "AAA", "broker": "iol", "qty": 3.0, "avg_price": 8.0, "currency": "USD"}
                ],
                "cash": {"USD": 100.0},
                "cash_by_broker": {"iol": {"USD": 100.0}},
            }
            positions_path.write_text(json.dumps(positions_payload), encoding="utf-8")

            execute_plan(
                run_id=run_id,
                base_path=str(root / "runs"),
                paper=True,
                base_root=root,
            )

            results_path = root / "runs" / run_id / "artifacts" / "execution.results.v1.0.0.json"
            self.assertTrue(results_path.exists())
            results_payload = json.loads(results_path.read_text(encoding="utf-8"))
            results = results_payload.get("results", [])
            self.assertEqual(len(results), 2)

            snapshot_before_path = root / "runs" / run_id / "artifacts" / "positions_snapshot_before.json"
            self.assertTrue(snapshot_before_path.exists())
            snapshot_path = root / "runs" / run_id / "artifacts" / "positions_snapshot_after.json"
            self.assertTrue(snapshot_path.exists())
            snapshot_payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
            self.assertAlmostEqual(float(snapshot_payload["cash"]["USD"]), 113.0, places=6)
            positions_after = {row["asset_id"]: row for row in snapshot_payload.get("positions", [])}
            self.assertAlmostEqual(float(positions_after["AAA"]["qty"]), 1.0, places=6)
            self.assertAlmostEqual(float(positions_after["BBB"]["qty"]), 1.0, places=6)

            execute_plan(
                run_id=run_id,
                base_path=str(root / "runs"),
                paper=True,
                base_root=root,
            )
            snapshot_payload_second = json.loads(snapshot_path.read_text(encoding="utf-8"))
            positions_after_second = {row["asset_id"]: row for row in snapshot_payload_second.get("positions", [])}
            self.assertAlmostEqual(float(positions_after_second["AAA"]["qty"]), 1.0, places=6)
            self.assertAlmostEqual(float(positions_after_second["BBB"]["qty"]), 1.0, places=6)

    def test_kill_switch_blocks_execution(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_id = "20260101-0931"
            plan_path = root / "runs" / run_id / "artifacts" / "execution.plan.v1.0.0.json"
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_payload = {
                "schema_version": "1.0.0",
                "reader_min_version": "1.0.0",
                "run_id": run_id,
                "asof_date": "2026-01-01",
                "execution_date": "2026-01-02",
                "execution_hour": "0931",
                "orders": [],
            }
            plan_path.write_text(json.dumps(plan_payload), encoding="utf-8")

            kill_path = root / "data" / "controls" / "kill_switch.json"
            kill_path.parent.mkdir(parents=True, exist_ok=True)
            kill_path.write_text(json.dumps({"enabled": True}), encoding="utf-8")

            with self.assertRaises(RuntimeError):
                execute_plan(
                    run_id=run_id,
                    base_path=str(root / "runs"),
                    paper=True,
                    base_root=root,
                )

    def test_reuses_run_id_but_keeps_only_current_plan_results(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_id = "20260101-0932"
            run_root = root / "runs" / run_id / "artifacts"
            run_root.mkdir(parents=True, exist_ok=True)

            positions_path = root / "data" / "results" / "positions.json"
            positions_path.parent.mkdir(parents=True, exist_ok=True)
            positions_path.write_text(
                json.dumps(
                    {
                        "positions": [],
                        "cash": {"USD": 100.0},
                        "cash_by_broker": {"iol": {"USD": 100.0}},
                    }
                ),
                encoding="utf-8",
            )

            first_plan = {
                "schema_version": "1.0.0",
                "reader_min_version": "1.0.0",
                "run_id": run_id,
                "asof_date": "2026-01-01",
                "execution_date": "2026-01-02",
                "execution_hour": "0932",
                "orders": [
                    {
                        "order_id": "old-buy",
                        "asset_id": "AAA",
                        "ticker": "AAA",
                        "broker_selected": "iol",
                        "order_side": "BUY",
                        "order_status": "READY",
                        "order_qty": 1.0,
                        "price_used": 10.0,
                        "currency": "USD",
                        "fees_estimated_usd": 1.0,
                    }
                ],
            }
            plan_path = run_root / "execution.plan.v1.0.0.json"
            plan_path.write_text(json.dumps(first_plan), encoding="utf-8")

            execute_plan(
                run_id=run_id,
                base_path=str(root / "runs"),
                paper=True,
                base_root=root,
            )

            second_plan = {
                **first_plan,
                "orders": [
                    {
                        "order_id": "new-buy",
                        "asset_id": "BBB",
                        "ticker": "BBB",
                        "broker_selected": "iol",
                        "order_side": "BUY",
                        "order_status": "READY",
                        "order_qty": 1.0,
                        "price_used": 20.0,
                        "currency": "USD",
                        "fees_estimated_usd": 1.0,
                    }
                ],
            }
            plan_path.write_text(json.dumps(second_plan), encoding="utf-8")
            positions_path.write_text(
                json.dumps(
                    {
                        "positions": [],
                        "cash": {"USD": 100.0},
                        "cash_by_broker": {"iol": {"USD": 100.0}},
                    }
                ),
                encoding="utf-8",
            )

            execute_plan(
                run_id=run_id,
                base_path=str(root / "runs"),
                paper=True,
                base_root=root,
            )

            results_payload = json.loads(
                (run_root / "execution.results.v1.0.0.json").read_text(encoding="utf-8")
            )
            results = results_payload.get("results", [])
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["order_id"], "new-buy")


if __name__ == "__main__":
    unittest.main()
