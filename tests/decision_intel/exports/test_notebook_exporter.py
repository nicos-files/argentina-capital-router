import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.contracts.manifests.config_snapshot import write_config_snapshot
from src.decision_intel.contracts.metadata_models import CURRENT_SCHEMA_VERSION, MIN_READER_VERSION
from src.decision_intel.decision.output_writer import write_decision_outputs
from src.decision_intel.evaluation.metrics_writer import write_evaluation_metrics
from src.decision_intel.exports.notebook_exporter import export_notebook_artifacts


class NotebookExporterTests(unittest.TestCase):
    def test_notebook_exports_idempotent(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            run_id = "run-1"
            run_root = base / run_id
            config_snapshot = write_config_snapshot(run_id, {"strategy_id": "s1"}, base_path=str(base))
            decision_path, decision_entry = write_decision_outputs(
                run_id=run_id,
                decisions=[{"asset_id": "AAPL", "signal": 1.0, "size": 10}],
                strategy_id="s1",
                variant_id=None,
                horizon="SHORT",
                rule_refs={"sizing_rule": "size.fixed", "constraints": [], "filters": []},
                config_snapshot_path=str(config_snapshot),
                base_path=str(base),
            )
            eval_path, eval_entry = write_evaluation_metrics(
                run_id=run_id,
                strategy_id="s1",
                variant_id=None,
                horizon="SHORT",
                metrics={"return": 0.1},
                base_path=str(base),
            )

            manifest = {
                "schema_version": CURRENT_SCHEMA_VERSION,
                "reader_min_version": MIN_READER_VERSION,
                "run_id": run_id,
                "status": "SUCCESS",
                "timestamps": {"created_at": "2026-01-01T00:00:00+00:00"},
                "config": {"snapshot_path": str(config_snapshot)},
                "data_snapshot_ids": {},
                "artifact_index": [
                    {**decision_entry, "path": str(Path(decision_path).relative_to(run_root))},
                    {**eval_entry, "path": str(Path(eval_path).relative_to(run_root))},
                ],
                "skips": [],
            }
            manifest_path = run_root / "manifests" / f"run_manifest.v{CURRENT_SCHEMA_VERSION}.json"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            export_notebook_artifacts(run_id=run_id, base_path=str(base))
            updated = json.loads(manifest_path.read_text(encoding="utf-8"))
            notebook_entries = [e for e in updated["artifact_index"] if e["name"].startswith("notebook.")]
            self.assertEqual(len(notebook_entries), 2)
            for entry in notebook_entries:
                self.assertFalse(Path(entry["path"]).is_absolute())
                self.assertTrue((run_root / entry["path"]).exists())
                self.assertTrue(entry["path"].startswith("artifacts/notebook/"))
                if entry["type"] == "notebook.parquet":
                    self.assertTrue(entry["path"].endswith(".parquet"))
                if entry["type"] == "notebook.csv":
                    self.assertTrue(entry["path"].endswith(".csv"))
                if entry["type"] == "notebook.json":
                    self.assertTrue(entry["path"].endswith(".json"))

            export_notebook_artifacts(run_id=run_id, base_path=str(base))
            updated_again = json.loads(manifest_path.read_text(encoding="utf-8"))
            notebook_entries_again = [e for e in updated_again["artifact_index"] if e["name"].startswith("notebook.")]
            entries = {(e["name"], e["type"], e["path"]) for e in notebook_entries}
            entries_again = {(e["name"], e["type"], e["path"]) for e in notebook_entries_again}
            self.assertEqual(entries_again, entries)


if __name__ == "__main__":
    unittest.main()
