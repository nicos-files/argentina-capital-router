import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.guards.determinism import (
    GuardrailViolation,
    compare_decision_outputs,
    require_data_snapshot_ids_stable,
    validate_config_snapshot_immutable,
)
from src.decision_intel.contracts.metadata_models import RunStatus


class DeterminismGuardTests(unittest.TestCase):
    def test_config_snapshot_hash_mismatch(self):
        with TemporaryDirectory() as tmp:
            snapshot_path = Path(tmp) / "config.snapshot.v1.0.0.json"
            snapshot_path.write_text("{\"a\":1}", encoding="utf-8")
            manifest = {"status": RunStatus.RUNNING.value, "skips": []}
            with self.assertRaises(GuardrailViolation):
                validate_config_snapshot_immutable(
                    manifest,
                    snapshot_path,
                    expected_hash="deadbeef",
                )
            self.assertEqual(manifest["status"], RunStatus.FAILED.value)
            self.assertEqual(manifest["skips"][0]["code"], "CONFIG_SNAPSHOT_MUTATED")

    def test_data_snapshot_ids_missing(self):
        manifest = {"status": RunStatus.RUNNING.value, "skips": []}
        with self.assertRaises(GuardrailViolation):
            require_data_snapshot_ids_stable(manifest, {})
        self.assertEqual(manifest["status"], RunStatus.FAILED.value)
        self.assertEqual(manifest["skips"][0]["code"], "MISSING_DATA_SNAPSHOT_IDS")

    def test_data_snapshot_ids_present(self):
        manifest = {"status": RunStatus.RUNNING.value, "skips": []}
        require_data_snapshot_ids_stable(manifest, {"features": "snap-1"})
        self.assertEqual(manifest["data_snapshot_ids"]["features"], "snap-1")

    def test_compare_decision_outputs(self):
        baseline = [{"ticker": "A", "weight": 0.5}, {"ticker": "B", "weight": 0.5}]
        candidate = [{"weight": 0.5, "ticker": "B"}, {"weight": 0.5, "ticker": "A"}]
        self.assertTrue(compare_decision_outputs(baseline, candidate))


if __name__ == "__main__":
    unittest.main()
