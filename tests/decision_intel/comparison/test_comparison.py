import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.comparison.comparator import compare_normalized
from src.decision_intel.comparison.comparison_writer import write_comparison


class ComparisonTests(unittest.TestCase):
    def test_delta_math(self):
        baseline = {"return": 0.1}
        candidate = {"return": 0.3}
        result = compare_normalized(baseline, candidate)
        self.assertEqual(result.deltas["return"], 0.2)

    def test_null_handling(self):
        baseline = {"return": 0.1}
        candidate = {"drawdown": -0.2}
        result = compare_normalized(baseline, candidate)
        self.assertIsNone(result.deltas["return"])
        self.assertIsNone(result.deltas["drawdown"])

    def test_writer_payload_and_manifest_entry(self):
        baseline = {"strategy_id": "s1", "variant_id": None}
        candidate = {"strategy_id": "s2", "variant_id": "v1"}
        result = compare_normalized({"return": 0.1}, {"return": 0.3})
        with TemporaryDirectory() as tmp:
            path, entry = write_comparison("run-1", baseline, candidate, result, base_path=tmp)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["baseline"]["strategy_id"], "s1")
            self.assertEqual(entry["name"], "evaluation.comparison")


if __name__ == "__main__":
    unittest.main()
