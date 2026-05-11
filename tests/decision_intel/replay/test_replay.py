import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.contracts.decisions.decision_constants import SCHEMA_VERSION as DECISION_SCHEMA_VERSION
from src.decision_intel.contracts.metadata_models import CURRENT_SCHEMA_VERSION, MIN_READER_VERSION
from src.decision_intel.contracts.manifests.config_snapshot import write_config_snapshot
from src.decision_intel.replay.replayer import replay_run
from src.decision_intel.contracts.signals.signal_loader import load_signal_input
from src.decision_intel.contracts.strategies.strategy_loader import load_strategy_config
from src.decision_intel.decision.engine import run_decision_engine
from src.decision_intel.decision.output_writer import write_decision_outputs
from src.decision_intel.decision.rules.builtin import (
    constraint_max_positions,
    filter_min_liquidity,
    sizing_fixed,
)
from src.decision_intel.decision.rules.registry import RuleRegistry


def _load_fixture(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_manifest(run_root: Path, payload: dict) -> Path:
    manifests_dir = run_root / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifests_dir / f"run_manifest.v{CURRENT_SCHEMA_VERSION}.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    return manifest_path


def _write_signals(run_root: Path, payload: dict) -> Path:
    signals_path = run_root / "inputs" / "signals.json"
    signals_path.parent.mkdir(parents=True, exist_ok=True)
    signals_path.write_text(json.dumps(payload), encoding="utf-8")
    return signals_path


class ReplayRunTests(unittest.TestCase):
    def test_replay_identical_outputs(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            run_id = "run-1"
            run_root = base / run_id
            config_snapshot = write_config_snapshot(
                run_id,
                _load_fixture("tests/decision_intel/fixtures/strategy_config.example.json"),
                base_path=str(base),
            )
            config_target = run_root / "config" / "snapshot.json"
            config_target.parent.mkdir(parents=True, exist_ok=True)
            config_target.write_text(Path(config_snapshot).read_text(encoding="utf-8"), encoding="utf-8")
            signals_path = _write_signals(
                run_root,
                _load_fixture("tests/decision_intel/fixtures/signal_input.example.json"),
            )

            # Create an original decision output using the stored inputs/configs.
            strategy = load_strategy_config(str(config_snapshot))
            signals = load_signal_input(str(signals_path))
            registry = RuleRegistry()
            registry.register_sizing("size.fixed", sizing_fixed)
            registry.register_constraint("risk.max_positions", constraint_max_positions)
            registry.register_filter("eligibility.liquid", filter_min_liquidity)
            rules = registry.resolve(
                sizing_rule=strategy.rules.sizing_rule,
                constraints=strategy.rules.constraints,
                filters=strategy.rules.filters,
            )
            decisions = run_decision_engine(
                strategy=strategy,
                signals=signals["signals"],
                rules=rules,
                rule_configs={"sizing_rule": {}, "constraints": {}, "filters": {}},
            )
            original_output, _ = write_decision_outputs(
                run_id=run_id,
                decisions=[d.__dict__ for d in decisions],
                strategy_id=strategy.strategy_id,
                variant_id=strategy.variant_id,
                horizon=strategy.horizon,
                rule_refs={
                    "sizing_rule": strategy.rules.sizing_rule,
                    "constraints": strategy.rules.constraints,
                    "filters": strategy.rules.filters,
                },
                config_snapshot_path=str(config_target),
                base_path=str(base),
            )
            original_entry = {
                "name": "decision.outputs",
                "type": "decisions",
                "path": str(original_output),
                "schema_version": DECISION_SCHEMA_VERSION,
            }
            manifest_payload = {
                "schema_version": CURRENT_SCHEMA_VERSION,
                "reader_min_version": MIN_READER_VERSION,
                "run_id": run_id,
                "status": "SUCCESS",
                "timestamps": {"created_at": "2026-01-01T00:00:00+00:00"},
                "config": {"snapshot_path": "config/snapshot.json"},
                "data_snapshot_ids": {},
                "artifact_index": [
                    {"name": "signals.input", "type": "signals", "path": str(signals_path), "schema_version": "1.0.0"},
                    original_entry,
                    {"name": "report.md", "type": "report", "path": "reports/report.md", "schema_version": "1.0.0"},
                ],
                "skips": [],
            }
            report_path = run_root / "reports" / "report.md"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text("report", encoding="utf-8")
            _write_manifest(run_root, manifest_payload)

            final_report = replay_run(run_id=run_id, base_path=str(base), replay_id="replay-1")
            payload = json.loads(Path(final_report.report_path).read_text(encoding="utf-8"))
            self.assertEqual(payload["match_status"], "IDENTICAL")
            self.assertEqual(payload["results"][0]["result"], "IDENTICAL")
            self.assertEqual(payload["compared_artifacts"], ["decision.outputs"])
            self.assertFalse((run_root / "replay").exists())
            self.assertIn(str(base / "replays"), final_report.report_path)

    def test_replay_reports_differences(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            run_id = "run-2"
            run_root = base / run_id
            config_snapshot = write_config_snapshot(
                run_id,
                _load_fixture("tests/decision_intel/fixtures/strategy_config.example.json"),
                base_path=str(base),
            )
            signals_path = _write_signals(
                run_root,
                _load_fixture("tests/decision_intel/fixtures/signal_input.example.json"),
            )

            original_output = run_root / "artifacts" / f"decision.outputs.v{DECISION_SCHEMA_VERSION}.json"
            original_output.parent.mkdir(parents=True, exist_ok=True)
            original_output.write_text(
                json.dumps(
                    {
                        "schema_version": DECISION_SCHEMA_VERSION,
                        "reader_min_version": "1.0.0",
                        "run_id": run_id,
                        "strategy_id": "strategy_alpha",
                        "variant_id": "v1",
                        "horizon": "SHORT",
                        "rule_refs": {"sizing_rule": "size.fixed", "constraints": [], "filters": []},
                        "config_snapshot_path": str(config_snapshot),
                        "decisions": [],
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            manifest_payload = {
                "schema_version": CURRENT_SCHEMA_VERSION,
                "reader_min_version": MIN_READER_VERSION,
                "run_id": run_id,
                "status": "SUCCESS",
                "timestamps": {"created_at": "2026-01-01T00:00:00+00:00"},
                "config": {"snapshot_path": str(config_snapshot)},
                "data_snapshot_ids": {},
                "artifact_index": [
                    {"name": "signals.input", "type": "signals", "path": str(signals_path), "schema_version": "1.0.0"},
                    {
                        "name": "decision.outputs",
                        "type": "decisions",
                        "path": str(original_output),
                        "schema_version": DECISION_SCHEMA_VERSION,
                    },
                ],
                "skips": [],
            }
            _write_manifest(run_root, manifest_payload)

            report = replay_run(run_id=run_id, base_path=str(base), replay_id="replay-2")
            payload = json.loads(Path(report.report_path).read_text(encoding="utf-8"))
            self.assertEqual(payload["match_status"], "DIFFERENT")
            self.assertEqual(payload["results"][0]["result"], "DIFFERENT")
            self.assertTrue(payload["results"][0]["differences"])
            self.assertFalse((run_root / "replay").exists())
            self.assertIn(str(base / "replays"), report.report_path)


if __name__ == "__main__":
    unittest.main()
