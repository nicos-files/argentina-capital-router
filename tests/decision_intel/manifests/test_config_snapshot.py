import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.contracts.manifests.config_snapshot import (
    MissingDataSnapshotIdsError,
    apply_config_snapshot_to_manifest,
    require_data_snapshot_ids,
    write_config_snapshot,
)
from src.decision_intel.contracts.metadata_models import CURRENT_SCHEMA_VERSION, RunStatus


class ConfigSnapshotTests(unittest.TestCase):
    def test_write_config_snapshot_deterministic(self):
        with TemporaryDirectory() as tmp:
            config = {"b": 2, "a": 1}
            path = write_config_snapshot("run-1", config, base_path=tmp)
            self.assertTrue(path.exists())
            expected = json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            self.assertEqual(path.read_text(encoding="utf-8"), expected)
            self.assertIn(f"config.snapshot.v{CURRENT_SCHEMA_VERSION}.json", str(path))

    def test_apply_config_snapshot_to_manifest(self):
        with TemporaryDirectory() as tmp:
            manifest = {"status": RunStatus.CREATED.value}
            path = Path(tmp) / "manifests" / "config.snapshot.v1.0.0.json"
            updated = apply_config_snapshot_to_manifest(manifest, path)
            self.assertEqual(updated["config"]["snapshot_path"], str(path))

    def test_require_data_snapshot_ids_missing(self):
        manifest = {"status": RunStatus.RUNNING.value}
        with self.assertRaises(MissingDataSnapshotIdsError) as ctx:
            require_data_snapshot_ids(manifest, {})
        self.assertEqual(ctx.exception.error_code, "MISSING_DATA_SNAPSHOT_IDS")
        self.assertEqual(manifest["status"], RunStatus.FAILED.value)
        self.assertEqual(manifest["error"]["error_code"], "MISSING_DATA_SNAPSHOT_IDS")

    def test_require_data_snapshot_ids_present(self):
        manifest = {"status": RunStatus.RUNNING.value}
        data_snapshot_ids = {"features": "snapshot-123"}
        require_data_snapshot_ids(manifest, data_snapshot_ids)
        self.assertEqual(manifest["data_snapshot_ids"], data_snapshot_ids)


if __name__ == "__main__":
    unittest.main()
