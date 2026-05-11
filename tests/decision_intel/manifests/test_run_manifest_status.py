import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.contracts.manifests.run_manifest_writer import (
    initialize_manifest,
    update_manifest_error,
    update_manifest_status,
)
from src.decision_intel.contracts.metadata_models import RunStatus


class RunManifestStatusTests(unittest.TestCase):
    def test_status_transitions_success(self):
        manifest = initialize_manifest("run-1", "config.snapshot.v1.0.0.json")
        self.assertIsNotNone(manifest.timestamps.created_at)
        self.assertIsNone(manifest.timestamps.started_at)
        self.assertIsNone(manifest.timestamps.completed_at)
        self.assertIsNone(manifest.error)

        manifest = update_manifest_status(manifest, RunStatus.RUNNING)
        self.assertEqual(manifest.status, RunStatus.RUNNING)
        self.assertIsNotNone(manifest.timestamps.started_at)
        self.assertIsNone(manifest.timestamps.completed_at)
        self.assertIsNone(manifest.error)
        first_started_at = manifest.timestamps.started_at

        manifest = update_manifest_status(manifest, RunStatus.RUNNING)
        self.assertEqual(manifest.timestamps.started_at, first_started_at)
        self.assertIsNone(manifest.timestamps.completed_at)

        manifest = update_manifest_status(manifest, RunStatus.SUCCESS)
        self.assertEqual(manifest.status, RunStatus.SUCCESS)
        self.assertIsNotNone(manifest.timestamps.completed_at)
        self.assertIsNone(manifest.error)
        first_completed_at = manifest.timestamps.completed_at

        manifest = update_manifest_status(manifest, RunStatus.SUCCESS)
        self.assertEqual(manifest.timestamps.completed_at, first_completed_at)
        self.assertIsNone(manifest.error)

    def test_status_transitions_failed_with_error(self):
        manifest = initialize_manifest("run-2", "config.snapshot.v1.0.0.json")
        manifest = update_manifest_status(manifest, RunStatus.RUNNING)
        manifest = update_manifest_status(manifest, RunStatus.FAILED)
        manifest = update_manifest_error(manifest, "FAILURE", "pipeline failed")
        self.assertEqual(manifest.status, RunStatus.FAILED)
        self.assertIsNotNone(manifest.timestamps.completed_at)
        self.assertIsNotNone(manifest.error)
        self.assertEqual(manifest.error["error_code"], "FAILURE")
        self.assertEqual(manifest.error["message"], "pipeline failed")

    def test_status_transitions_skipped(self):
        manifest = initialize_manifest("run-3", "config.snapshot.v1.0.0.json")
        manifest = update_manifest_status(manifest, RunStatus.RUNNING)
        manifest = update_manifest_status(manifest, RunStatus.SKIPPED)
        self.assertEqual(manifest.status, RunStatus.SKIPPED)
        self.assertIsNotNone(manifest.timestamps.completed_at)
        self.assertIsNone(manifest.error)

    def test_running_idempotency(self):
        manifest = initialize_manifest("run-4", "config.snapshot.v1.0.0.json")
        manifest = update_manifest_status(manifest, RunStatus.RUNNING)
        first_started_at = manifest.timestamps.started_at
        manifest = update_manifest_status(manifest, RunStatus.RUNNING)
        self.assertEqual(manifest.timestamps.started_at, first_started_at)
        self.assertIsNone(manifest.timestamps.completed_at)

    def test_skipped_terminal_transition(self):
        manifest = initialize_manifest("run-5", "config.snapshot.v1.0.0.json")
        manifest = update_manifest_status(manifest, RunStatus.RUNNING)
        manifest = update_manifest_status(manifest, RunStatus.SKIPPED)
        self.assertEqual(manifest.status, RunStatus.SKIPPED)
        self.assertIsNotNone(manifest.timestamps.completed_at)
        self.assertIsNotNone(manifest.timestamps.started_at)

    def test_terminal_idempotency(self):
        manifest = initialize_manifest("run-6", "config.snapshot.v1.0.0.json")
        manifest = update_manifest_status(manifest, RunStatus.RUNNING)
        manifest = update_manifest_status(manifest, RunStatus.SUCCESS)
        first_completed_at = manifest.timestamps.completed_at
        manifest = update_manifest_status(manifest, RunStatus.SUCCESS)
        self.assertEqual(manifest.timestamps.completed_at, first_completed_at)


if __name__ == "__main__":
    unittest.main()
