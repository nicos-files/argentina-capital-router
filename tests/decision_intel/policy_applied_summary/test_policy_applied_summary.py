import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.policy_applied_summary.policy_applied_summary_writer import (
    write_policy_applied_summary,
)
from src.decision_intel.policy_applied_summary.summarizer import summarize_policy_applied


def _policy_applied_metrics():
    return {
        "return": {
            "delta": 0.2,
            "oriented_delta": 0.2,
            "thresholds": {"min": 0.1},
            "thresholds_met": True,
        },
        "drawdown": {
            "delta": 0.05,
            "oriented_delta": -0.05,
            "thresholds": {"max": -0.1},
            "thresholds_met": False,
        },
        "turnover": {
            "delta": None,
            "oriented_delta": None,
            "thresholds": {"max": 0.2},
            "thresholds_met": None,
        },
        "volatility": {
            "delta": 0.0,
            "oriented_delta": 0.0,
            "thresholds": None,
            "thresholds_met": None,
        },
    }


class PolicyAppliedSummaryTests(unittest.TestCase):
    def test_summarize_policy_applied(self):
        summary = summarize_policy_applied(_policy_applied_metrics())
        self.assertEqual(summary.total_policy_metrics, 4)
        self.assertEqual(summary.metrics_with_null_delta, 1)
        self.assertEqual(summary.metrics_with_non_null_delta, 3)
        self.assertEqual(summary.thresholds_defined_count, 3)
        self.assertEqual(summary.thresholds_met_count, 1)
        self.assertEqual(summary.thresholds_failed_count, 1)
        self.assertEqual(summary.thresholds_unknown_count, 1)
        self.assertEqual(summary.oriented_delta_positive_count, 1)
        self.assertEqual(summary.oriented_delta_negative_count, 1)
        self.assertEqual(summary.oriented_delta_zero_count, 1)
        self.assertEqual(summary.oriented_delta_null_count, 1)
        self.assertEqual(summary.null_delta_metrics, ["turnover"])
        self.assertEqual(summary.thresholds_failed_metrics, ["drawdown"])
        self.assertEqual(summary.thresholds_unknown_metrics, ["turnover"])

    def test_write_policy_applied_summary(self):
        baseline = {"strategy_id": "s1", "variant_id": None}
        candidate = {"strategy_id": "s2", "variant_id": "v1"}
        with TemporaryDirectory() as tmp:
            path, entry = write_policy_applied_summary(
                run_id="run-1",
                policy_id="policy-1",
                baseline=baseline,
                candidate=candidate,
                policy_applied_metrics=_policy_applied_metrics(),
                base_path=tmp,
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["summary"]["thresholds_failed_count"], 1)
            self.assertEqual(entry["name"], "evaluation.policy_applied_summary")


if __name__ == "__main__":
    unittest.main()
