import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.contracts.metadata_models import CURRENT_SCHEMA_VERSION, MIN_READER_VERSION
from src.decision_intel.decision.output_writer import write_decision_outputs
from src.decision_intel.evaluation.metrics_writer import write_evaluation_metrics
from src.decision_intel.reports.generator import generate_reports


class ReportGeneratorTests(unittest.TestCase):
    def test_generate_reports(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            run_id = "run-1"
            decision_path, decision_entry = write_decision_outputs(
                run_id=run_id,
                decisions=[{"asset_id": "AAPL", "signal": 1.0}],
                strategy_id="s1",
                variant_id=None,
                horizon="SHORT",
                rule_refs={"sizing_rule": "size.fixed", "constraints": [], "filters": []},
                config_snapshot_path="config.snapshot.v1.0.0.json",
                base_path=str(base),
            )
            metrics_path, metrics_entry = write_evaluation_metrics(
                run_id=run_id,
                strategy_id="s1",
                variant_id=None,
                horizon="SHORT",
                metrics={"return": 0.1},
                base_path=str(base),
            )
            run_root = base / run_id
            manifest = {
                "schema_version": CURRENT_SCHEMA_VERSION,
                "reader_min_version": MIN_READER_VERSION,
                "run_id": run_id,
                "status": "SUCCESS",
                "timestamps": {"created_at": "2026-01-01T00:00:00+00:00"},
                "config": {"snapshot_path": "config.snapshot.v1.0.0.json"},
                "data_snapshot_ids": {},
                "artifact_index": [
                    {**decision_entry, "path": str(Path(decision_path).relative_to(run_root))},
                    {**metrics_entry, "path": str(Path(metrics_path).relative_to(run_root))},
                ],
                "skips": [],
            }
            manifest_path = run_root / "manifests" / f"run_manifest.v{CURRENT_SCHEMA_VERSION}.json"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            md_path, html_path = generate_reports(run_id=run_id, base_path=str(base))
            self.assertTrue(md_path.exists())
            self.assertTrue(html_path.exists())
            md_text = md_path.read_text(encoding="utf-8")
            html_text = html_path.read_text(encoding="utf-8")
            self.assertIn("run_id: run-1", md_text)
            self.assertIn("decision.outputs", md_text)
            self.assertIn("evaluation.metrics", md_text)
            self.assertIn("Run Report", html_text)


if __name__ == "__main__":
    unittest.main()
