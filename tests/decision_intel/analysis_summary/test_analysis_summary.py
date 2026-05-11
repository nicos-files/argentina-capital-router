import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.analysis_summary.analyzer import summarize_comparison
from src.decision_intel.analysis_summary.analysis_writer import write_analysis_summary


class AnalysisSummaryTests(unittest.TestCase):
    def test_summarize_comparison(self):
        comparison_metrics = {
            "return": {"baseline": 0.1, "candidate": 0.3, "delta": 0.2},
            "drawdown": {"baseline": None, "candidate": -0.2, "delta": None},
        }
        summary = summarize_comparison(comparison_metrics)
        self.assertEqual(summary.total_metrics, 2)
        self.assertEqual(summary.compared_metrics, 1)
        self.assertEqual(summary.null_delta_count, 1)
        self.assertEqual(summary.null_delta_metrics, ["drawdown"])

    def test_write_analysis_summary(self):
        comparison_metrics = {
            "return": {"baseline": 0.1, "candidate": 0.3, "delta": 0.2},
            "drawdown": {"baseline": None, "candidate": -0.2, "delta": None},
        }
        summary = summarize_comparison(comparison_metrics)
        baseline = {"strategy_id": "s1", "variant_id": None}
        candidate = {"strategy_id": "s2", "variant_id": "v1"}
        with TemporaryDirectory() as tmp:
            path, entry = write_analysis_summary(
                run_id="run-1",
                baseline=baseline,
                candidate=candidate,
                summary=summary,
                base_path=tmp,
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["summary"]["null_delta_count"], 1)
            self.assertEqual(entry["name"], "evaluation.analysis_summary")


if __name__ == "__main__":
    unittest.main()
