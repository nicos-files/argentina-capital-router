import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.contracts.metadata_models import CURRENT_SCHEMA_VERSION, MIN_READER_VERSION


def _parse_version(version: str):
    return tuple(int(part) for part in version.split("."))


def _load_schema():
    schema_path = Path("src/decision_intel/contracts/manifests/run_manifest.schema.json")
    return json.loads(schema_path.read_text(encoding="utf-8"))


class ManifestSchemaTests(unittest.TestCase):
    def test_manifest_schema_required_fields(self):
        schema = _load_schema()
        required = set(schema["required"])
        expected = {
            "schema_version",
            "reader_min_version",
            "run_id",
            "status",
            "timestamps",
            "config",
            "data_snapshot_ids",
            "artifact_index",
            "skips",
        }
        self.assertTrue(expected.issubset(required))

    def test_manifest_schema_versioning(self):
        schema = _load_schema()
        self.assertEqual(schema["properties"]["schema_version"]["const"], CURRENT_SCHEMA_VERSION)
        self.assertEqual(schema["properties"]["reader_min_version"]["const"], MIN_READER_VERSION)

    def test_backward_compat_reader_gating(self):
        self.assertLessEqual(_parse_version(MIN_READER_VERSION), _parse_version(CURRENT_SCHEMA_VERSION))


if __name__ == "__main__":
    unittest.main()
