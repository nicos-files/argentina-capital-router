import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.evaluation.runner import run_evaluation_from_manifest
from src.decision_intel.contracts.decisions.decision_constants import DECISION_ARTIFACT_NAME


class MetricsRunnerTests(unittest.TestCase):
    def test_run_evaluation_from_manifest(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            run_id = "run-1"
            manifest_path = base / run_id / "manifests" / "run_manifest.v1.0.0.json"
            artifacts_path = base / run_id / "artifacts"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            artifacts_path.mkdir(parents=True, exist_ok=True)

            decision_payload = {
                "schema_version": "1.0.0",
                "reader_min_version": "1.0.0",
                "run_id": run_id,
                "strategy_id": "strategy_alpha",
                "variant_id": None,
                "horizon": "SHORT",
                "rule_refs": {"sizing_rule": "size.fixed", "constraints": [], "filters": []},
                "config_snapshot_path": "runs/run-1/manifests/config.snapshot.v1.0.0.json",
                "decisions": [{"asset_id": "AAPL", "signal": 0.2, "outputs": {}}],
            }
            decision_path = artifacts_path / "decision.outputs.v1.0.0.json"
            decision_path.write_text(json.dumps(decision_payload), encoding="utf-8")

            manifest = {
                "schema_version": "1.0.0",
                "reader_min_version": "1.0.0",
                "run_id": run_id,
                "status": "SUCCESS",
                "timestamps": {"created_at": "2026-01-01T00:00:00Z"},
                "config": {"snapshot_path": "runs/run-1/manifests/config.snapshot.v1.0.0.json"},
                "data_snapshot_ids": {},
                "artifact_index": [
                    {
                        "name": DECISION_ARTIFACT_NAME,
                        "type": "decisions",
                        "path": str(decision_path),
                        "schema_version": "1.0.0",
                    }
                ],
                "skips": [],
            }
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            output_path = run_evaluation_from_manifest(manifest_path)
            self.assertTrue(output_path.exists())
            updated = json.loads(manifest_path.read_text(encoding="utf-8"))
            names = [a["name"] for a in updated["artifact_index"]]
            self.assertIn("evaluation.metrics", names)


if __name__ == "__main__":
    unittest.main()
