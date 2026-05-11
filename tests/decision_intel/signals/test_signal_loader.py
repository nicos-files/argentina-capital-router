import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.contracts.signals.signal_loader import (
    append_signal_artifact,
    load_signal_input,
)
from src.decision_intel.contracts.signals.signal_loader import SignalInputError


class SignalLoaderTests(unittest.TestCase):
    def test_load_signal_input_fixture(self):
        fixture = Path("tests/decision_intel/fixtures/signal_input.example.json")
        data = load_signal_input(fixture)
        self.assertEqual(data["horizon"], "SHORT")
        self.assertEqual(len(data["signals"]), 2)

    def test_invalid_signal_schema_version(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "signals.json"
            path.write_text(
                json.dumps({"schema_version": "9.9.9", "reader_min_version": "1.0.0", "horizon": "SHORT", "signals": []}),
                encoding="utf-8",
            )
            with self.assertRaises(SignalInputError) as ctx:
                load_signal_input(path)
            self.assertEqual(ctx.exception.error_code, "SCHEMA_VERSION_MISMATCH")

    def test_invalid_reader_min_version(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "signals.json"
            path.write_text(
                json.dumps({"schema_version": "1.0.0", "reader_min_version": "9.9.9", "horizon": "SHORT", "signals": []}),
                encoding="utf-8",
            )
            with self.assertRaises(SignalInputError) as ctx:
                load_signal_input(path)
            self.assertEqual(ctx.exception.error_code, "READER_MIN_VERSION_MISMATCH")

    def test_append_signal_artifact(self):
        manifest = {"artifact_index": []}
        updated = append_signal_artifact(manifest, "runs/r1/artifacts/signals.json", "hash123")
        self.assertEqual(len(updated["artifact_index"]), 1)
        self.assertEqual(updated["artifact_index"][0]["name"], "signals.input")
        self.assertEqual(updated["artifact_index"][0]["schema_version"], "1.0.0")


if __name__ == "__main__":
    unittest.main()
