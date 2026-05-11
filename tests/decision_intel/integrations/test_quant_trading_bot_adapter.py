import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.integrations.quant_trading_bot_adapter import build_decision_intel_artifacts


class QuantTradingBotAdapterTests(unittest.TestCase):
    def test_adapter_builds_manifest_and_reports(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            runs_root = base / "runs"
            outputs_root = base / "outputs"
            outputs_root.mkdir(parents=True, exist_ok=True)
            final_decision_path = outputs_root / "final_decision.json"
            backtest_summary_path = outputs_root / "backtest_summary.json"

            final_decision_path.write_text(
                json.dumps(
                    {
                        "long_term": [{"ticker": "AAPL", "peso_pct": 60, "justificacion": "ok"}],
                        "intraday": [{"ticker": "MSFT", "justificacion": "ok"}],
                    }
                ),
                encoding="utf-8",
            )
            backtest_summary_path.write_text(
                json.dumps({"ret_total": 0.1, "ret_daily_mean": 0.01, "max_drawdown": 0.05, "operations": 12}),
                encoding="utf-8",
            )

            result = build_decision_intel_artifacts(
                run_id="20260101-0930",
                base_path=str(runs_root),
                final_decision_path=final_decision_path,
                backtest_summary_path=backtest_summary_path,
                weights_json='{"AAPL":0.6,"MSFT":0.4}',
                config_snapshot_path="config.snapshot.v1.0.0.json",
            )

            manifest_path = result.manifest_path
            self.assertTrue(manifest_path.exists())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            names = {entry["name"] for entry in manifest.get("artifact_index", [])}
            self.assertIn("decision.outputs", names)
            self.assertIn("evaluation.metrics", names)
            self.assertIn("portfolio.aggregation", names)

            run_root = runs_root / "20260101-0930"
            self.assertTrue((run_root / "reports" / "run_report.md").exists())
            self.assertTrue((run_root / "reports" / "portfolio_report.md").exists())

    def test_adapter_persists_manifest_before_recommendations(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            runs_root = base / "runs"
            outputs_root = base / "outputs"
            outputs_root.mkdir(parents=True, exist_ok=True)
            final_decision_path = outputs_root / "final_decision.json"
            backtest_summary_path = outputs_root / "backtest_summary.json"

            final_decision_path.write_text(
                json.dumps(
                    {
                        "long_term": [{"ticker": "AAPL", "peso_pct": 60, "justificacion": "ok"}],
                        "intraday": [{"ticker": "MSFT", "justificacion": "ok"}],
                    }
                ),
                encoding="utf-8",
            )
            backtest_summary_path.write_text(
                json.dumps({"ret_total": 0.1, "ret_daily_mean": 0.01, "max_drawdown": 0.05, "operations": 12}),
                encoding="utf-8",
            )

            def _fake_write_recommendations(run_id, base_path="runs", **kwargs):
                manifest_path = Path(base_path) / run_id / "manifests" / "run_manifest.v1.0.0.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                names = {entry["name"] for entry in manifest.get("artifact_index", [])}
                self.assertIn("decision.outputs", names)
                self.assertIn("evaluation.metrics", names)
                rec_path = Path(base_path) / run_id / "artifacts" / "recommendation.outputs.v1.0.0.json"
                rec_path.parent.mkdir(parents=True, exist_ok=True)
                rec_path.write_text(json.dumps({"recommendations": []}), encoding="utf-8")
                return rec_path, {
                    "name": "recommendation.outputs",
                    "type": "recommendation.outputs",
                    "path": "artifacts/recommendation.outputs.v1.0.0.json",
                    "schema_version": "1.0.0",
                }

            def _fake_write_execution_plan(run_id, recommendations_path, base_path="runs"):
                plan_path = Path(base_path) / run_id / "artifacts" / "execution.plan.v1.0.0.json"
                plan_path.parent.mkdir(parents=True, exist_ok=True)
                plan_path.write_text(json.dumps({"orders": []}), encoding="utf-8")
                return plan_path, {
                    "name": "execution.plan",
                    "type": "execution.plan",
                    "path": "artifacts/execution.plan.v1.0.0.json",
                    "schema_version": "1.0.0",
                }

            with patch(
                "src.decision_intel.integrations.quant_trading_bot_adapter.write_recommendations",
                side_effect=_fake_write_recommendations,
            ), patch(
                "src.decision_intel.integrations.quant_trading_bot_adapter.write_execution_plan",
                side_effect=_fake_write_execution_plan,
            ):
                build_decision_intel_artifacts(
                    run_id="20260101-0935",
                    base_path=str(runs_root),
                    final_decision_path=final_decision_path,
                    backtest_summary_path=backtest_summary_path,
                    config_snapshot_path="config.snapshot.v1.0.0.json",
                    emit_recommendations=True,
                )


if __name__ == "__main__":
    unittest.main()
