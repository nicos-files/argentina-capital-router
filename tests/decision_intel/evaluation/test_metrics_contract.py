import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.contracts.evaluation.metrics_constants import SCHEMA_VERSION, EVAL_SCHEMA_ID
from src.decision_intel.evaluation.metrics import PassthroughMetricsCalculator
from src.decision_intel.evaluation.metrics_writer import write_evaluation_metrics


class MetricsContractTests(unittest.TestCase):
    def test_passthrough_calculator(self):
        calc = PassthroughMetricsCalculator()
        metrics = calc.compute({"return": 0.1})
        self.assertEqual(metrics["return"], 0.1)

    def test_write_evaluation_metrics(self):
        with TemporaryDirectory() as tmp:
            path, entry = write_evaluation_metrics(
                run_id="run-1",
                strategy_id="strategy_alpha",
                variant_id=None,
                horizon="SHORT",
                metrics={"return": 0.1},
                base_path=tmp,
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], SCHEMA_VERSION)
            self.assertEqual(entry["name"], "evaluation.metrics")

    def test_schema_id_matches_constant(self):
        schema_path = Path("src/decision_intel/contracts/evaluation/metrics.schema.json")
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(schema["$id"], EVAL_SCHEMA_ID)


if __name__ == "__main__":
    unittest.main()
