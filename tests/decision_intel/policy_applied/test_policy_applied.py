import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.policy_applied.evaluator import apply_policy_to_comparison
from src.decision_intel.policy_applied.policy_applied_writer import write_policy_applied


def _base_policy():
    return {
        "schema_version": "1.0.0",
        "reader_min_version": "1.0.0",
        "policy_id": "policy-1",
        "policy": {
            "metrics": {
                "return": {
                    "weight": 2.0,
                    "direction": "higher_is_better",
                    "thresholds": {"min": 0.1},
                },
                "drawdown": {
                    "weight": 1.5,
                    "direction": "lower_is_better",
                    "thresholds": {"max": -0.1},
                },
            }
        },
    }


class PolicyAppliedTests(unittest.TestCase):
    def test_apply_policy_per_metric(self):
        comparison_metrics = {
            "return": {"baseline": 0.1, "candidate": 0.3, "delta": 0.2},
            "drawdown": {"baseline": -0.2, "candidate": -0.15, "delta": 0.05},
        }
        result = apply_policy_to_comparison(_base_policy(), comparison_metrics)
        applied = result.applied_metrics
        self.assertEqual(result.policy_id, "policy-1")
        self.assertEqual(applied["return"]["oriented_delta"], 0.2)
        self.assertEqual(applied["return"]["weighted_delta"], 0.4)
        self.assertTrue(applied["return"]["thresholds_met"])
        self.assertEqual(applied["drawdown"]["oriented_delta"], -0.05)
        self.assertEqual(applied["drawdown"]["weighted_delta"], -0.075)
        self.assertTrue(applied["drawdown"]["thresholds_met"])

    def test_missing_comparison_metric(self):
        comparison_metrics = {"return": {"baseline": 0.1, "candidate": None, "delta": None}}
        result = apply_policy_to_comparison(_base_policy(), comparison_metrics)
        applied = result.applied_metrics
        self.assertIsNone(applied["drawdown"]["baseline"])
        self.assertIsNone(applied["drawdown"]["candidate"])
        self.assertIsNone(applied["drawdown"]["delta"])
        self.assertIsNone(applied["drawdown"]["oriented_delta"])
        self.assertIsNone(applied["drawdown"]["weighted_delta"])
        self.assertIsNone(applied["drawdown"]["thresholds_met"])

    def test_non_numeric_candidate_thresholds_unknown(self):
        comparison_metrics = {
            "return": {"baseline": 0.1, "candidate": "0.3", "delta": 0.2},
            "drawdown": {"baseline": -0.2, "candidate": -0.15, "delta": 0.05},
        }
        result = apply_policy_to_comparison(_base_policy(), comparison_metrics)
        applied = result.applied_metrics
        self.assertIsNone(applied["return"]["thresholds_met"])

    def test_write_policy_applied(self):
        comparison_metrics = {
            "return": {"baseline": 0.1, "candidate": 0.3, "delta": 0.2},
            "drawdown": {"baseline": -0.2, "candidate": -0.15, "delta": 0.05},
        }
        baseline = {"strategy_id": "s1", "variant_id": None}
        candidate = {"strategy_id": "s2", "variant_id": "v1"}
        with TemporaryDirectory() as tmp:
            path, entry = write_policy_applied(
                run_id="run-1",
                baseline=baseline,
                candidate=candidate,
                policy=_base_policy(),
                comparison_metrics=comparison_metrics,
                base_path=tmp,
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["policy_id"], "policy-1")
            self.assertEqual(entry["name"], "evaluation.policy_applied")


if __name__ == "__main__":
    unittest.main()
