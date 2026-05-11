import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.contracts.metadata_models import CURRENT_SCHEMA_VERSION
from src.decision_intel.run_history.enumerator import enumerate_runs


def _write_manifest(run_root: Path, payload: dict) -> None:
    manifests_dir = run_root / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifests_dir / f"run_manifest.v{CURRENT_SCHEMA_VERSION}.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")


class RunEnumeratorTests(unittest.TestCase):
    def test_enumerate_runs_order_and_fields(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_manifest(
                base / "run-a",
                {
                    "schema_version": "1.0.0",
                    "reader_min_version": "1.0.0",
                    "run_id": "run-a",
                    "status": "SUCCESS",
                    "strategy_id": "strat-1",
                    "horizon": "LONG",
                    "timestamps": {
                        "created_at": "2026-01-01T00:00:00+00:00",
                        "started_at": "2026-01-01T00:01:00+00:00",
                        "completed_at": "2026-01-01T00:02:00+00:00",
                    },
                    "config": {"snapshot_path": "snap-1.json"},
                    "data_snapshot_ids": {},
                    "artifact_index": [],
                    "skips": [],
                },
            )
            _write_manifest(
                base / "run-b",
                {
                    "schema_version": "1.0.0",
                    "reader_min_version": "1.0.0",
                    "run_id": "run-b",
                    "status": "FAILED",
                    "strategy_id": "strat-2",
                    "horizon": "SHORT",
                    "timestamps": {
                        "created_at": "2026-01-02T00:00:00+00:00",
                        "started_at": "2026-01-02T00:01:00+00:00",
                        "completed_at": "2026-01-02T00:02:00+00:00",
                    },
                    "config": {"snapshot_path": "snap-2.json"},
                    "data_snapshot_ids": {},
                    "artifact_index": [],
                    "skips": [],
                },
            )
            summaries = enumerate_runs(base_path=str(base))
            self.assertEqual([s.run_id for s in summaries], ["run-b", "run-a"])
            self.assertEqual(summaries[0].strategy_id, "strat-2")
            self.assertEqual(summaries[0].horizon, "SHORT")
            self.assertEqual(summaries[1].status, "SUCCESS")
            self.assertEqual(summaries[1].completed_at, "2026-01-01T00:02:00+00:00")

    def test_missing_manifest_is_skipped(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "run-missing").mkdir(parents=True, exist_ok=True)
            summaries = enumerate_runs(base_path=str(base))
            self.assertEqual(summaries, [])


if __name__ == "__main__":
    unittest.main()
