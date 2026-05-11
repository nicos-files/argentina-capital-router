import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.decision.output_writer import write_decision_outputs


class DecisionOutputWriterTests(unittest.TestCase):
    def test_write_decision_outputs(self):
        with TemporaryDirectory() as tmp:
            decisions = [
                {"asset_id": "AAPL", "signal": 0.5, "outputs": {"position_size": 1.0}},
                {"asset_id": "MSFT", "signal": -0.2, "outputs": {"position_size": 0.5}},
            ]
            rule_refs = {
                "sizing_rule": "size.fixed",
                "constraints": ["risk.max_positions"],
                "filters": ["eligibility.liquid"],
            }
            path, manifest_entry = write_decision_outputs(
                run_id="run-1",
                decisions=decisions,
                strategy_id="strategy_alpha",
                variant_id=None,
                horizon="SHORT",
                rule_refs=rule_refs,
                config_snapshot_path="runs/run-1/manifests/config.snapshot.v1.0.0.json",
                base_path=tmp,
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["strategy_id"], "strategy_alpha")
            self.assertEqual(payload["reader_min_version"], "1.0.0")
            self.assertEqual(payload["rule_refs"]["sizing_rule"], "size.fixed")
            self.assertEqual(manifest_entry["name"], "decision.outputs")
            self.assertEqual(manifest_entry["schema_version"], "1.0.0")

    def test_rule_refs_validation(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                write_decision_outputs(
                    run_id="run-1",
                    decisions=[],
                    strategy_id="strategy_alpha",
                    variant_id=None,
                    horizon="SHORT",
                    rule_refs={"sizing_rule": "size.fixed", "constraints": "bad", "filters": []},
                    config_snapshot_path="runs/run-1/manifests/config.snapshot.v1.0.0.json",
                    base_path=tmp,
                )


if __name__ == "__main__":
    unittest.main()
