import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.normalization.normalizer import normalize_mean
from src.decision_intel.normalization.normalized_writer import write_normalized_metrics


class NormalizationTests(unittest.TestCase):
    def test_normalize_mean(self):
        metrics = {
            "SHORT": {"return": 0.1, "drawdown": -0.05},
            "LONG": {"return": 0.3},
        }
        result = normalize_mean(metrics)
        self.assertEqual(result.normalized_metrics["return"], 0.2)
        self.assertEqual(result.normalized_metrics["drawdown"], -0.05)

    def test_write_normalized_metrics(self):
        metrics = {
            "SHORT": {"return": 0.1},
            "LONG": {"return": 0.3},
        }
        result = normalize_mean(metrics)
        with TemporaryDirectory() as tmp:
            path, entry = write_normalized_metrics(
                run_id="run-1",
                strategy_id="strategy_alpha",
                variant_id=None,
                result=result,
                base_path=tmp,
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["normalization"]["method"], "mean")
            self.assertEqual(entry["name"], "evaluation.normalized")


if __name__ == "__main__":
    unittest.main()
