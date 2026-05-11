import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.cli.run_decisions import main as run_cli


class RunDecisionsCLITests(unittest.TestCase):
    def test_run_decisions_creates_manifest_and_artifacts(self):
        with TemporaryDirectory() as tmp:
            base_path = Path(tmp)
            run_id = "run-1"

            strategy_path = base_path / "strategy.json"
            strategy_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0.0",
                        "strategy_id": "strategy_alpha",
                        "variant_id": "v1",
                        "horizon": "SHORT",
                        "assumptions": {},
                        "rules": {
                            "sizing_rule": "size.fixed",
                            "constraints": ["risk.max_positions"],
                            "filters": ["eligibility.liquid"],
                        },
                    }
                ),
                encoding="utf-8",
            )

            signals_path = base_path / "signals.json"
            signals_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0.0",
                        "reader_min_version": "1.0.0",
                        "horizon": "SHORT",
                        "signals": [{"asset_id": "AAPL", "signal": 0.1}],
                    }
                ),
                encoding="utf-8",
            )

            argv = [
                "run_decisions",
                "--run-id",
                run_id,
                "--strategy-config",
                str(strategy_path),
                "--signals",
                str(signals_path),
                "--data-snapshot-id",
                "snapshot-1",
                "--base-path",
                str(base_path),
            ]
            original_argv = sys.argv
            try:
                sys.argv = argv
                run_cli()
            finally:
                sys.argv = original_argv

            manifest_path = base_path / run_id / "manifests" / "run_manifest.v1.0.0.json"
            self.assertTrue(manifest_path.exists())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "SUCCESS")
            artifact_names = [a["name"] for a in manifest["artifact_index"]]
            self.assertIn("signals.input", artifact_names)
            self.assertIn("decision.outputs", artifact_names)

            decision_path = base_path / run_id / "artifacts" / "decision.outputs.v1.0.0.json"
            self.assertTrue(decision_path.exists())


if __name__ == "__main__":
    unittest.main()
