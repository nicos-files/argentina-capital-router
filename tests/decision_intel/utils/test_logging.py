import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.utils.logging import write_audit_event, write_run_event


class LoggingTests(unittest.TestCase):
    def test_run_event_written_with_required_fields(self):
        with TemporaryDirectory() as tmp:
            path = write_run_event(
                run_id="run-1",
                level="INFO",
                event_type="RUN_STARTED",
                message="run started",
                context={"foo": "bar"},
                base_path=tmp,
            )
            line = path.read_text(encoding="utf-8").strip()
            payload = json.loads(line)
            for key in ["timestamp_utc", "level", "event_type", "run_id", "message", "context"]:
                self.assertIn(key, payload)

    def test_audit_event_written_with_required_fields(self):
        with TemporaryDirectory() as tmp:
            path = write_audit_event(
                run_id="run-2",
                level="INFO",
                event_type="CONFIG_SNAPSHOT",
                message="config snapshot saved",
                context={"path": "manifests/config.snapshot.v1.0.0.json"},
                base_path=tmp,
            )
            line = path.read_text(encoding="utf-8").strip()
            payload = json.loads(line)
            for key in ["timestamp_utc", "level", "event_type", "run_id", "message", "context"]:
                self.assertIn(key, payload)

    def test_run_event_invalid_fields(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                write_run_event(
                    run_id="run-3",
                    level="",
                    event_type="RUN_STARTED",
                    message="run started",
                    context={},
                    base_path=tmp,
                )


if __name__ == "__main__":
    unittest.main()
