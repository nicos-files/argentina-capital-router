import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.contracts.metadata_models import CURRENT_SCHEMA_VERSION, MIN_READER_VERSION
from src.decision_intel.decision.output_writer import write_decision_outputs
from src.decision_intel.portfolio.aggregator import aggregate_portfolio
from src.decision_intel.portfolio.comparison import compare_portfolio


class PortfolioComparisonTests(unittest.TestCase):
    def test_compare_portfolio(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            run_id = "run-1"
            decision_path, decision_entry = write_decision_outputs(
                run_id=run_id,
                decisions=[
                    {"asset_id": "MSFT", "signal": 0.2},
                    {"asset_id": "AAPL", "signal": 0.8},
                ],
                strategy_id="s1",
                variant_id=None,
                horizon="SHORT",
                rule_refs={"sizing_rule": "size.fixed", "constraints": [], "filters": []},
                config_snapshot_path="config.snapshot.v1.0.0.json",
                base_path=str(base),
            )
            run_root = base / run_id
            manifest = {
                "schema_version": CURRENT_SCHEMA_VERSION,
                "reader_min_version": MIN_READER_VERSION,
                "run_id": run_id,
                "status": "SUCCESS",
                "timestamps": {"created_at": "2026-01-01T00:00:00+00:00"},
                "config": {"snapshot_path": "config.snapshot.v1.0.0.json"},
                "data_snapshot_ids": {},
                "artifact_index": [{**decision_entry, "path": str(Path(decision_path).relative_to(run_root))}],
                "skips": [],
            }
            manifest_path = run_root / "manifests" / f"run_manifest.v{CURRENT_SCHEMA_VERSION}.json"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            aggregate_portfolio(
                run_id=run_id,
                weights={"AAPL": 0.6, "MSFT": 0.4},
                base_path=str(base),
            )
            output_path, entry = compare_portfolio(run_id=run_id, base_path=str(base))
            self.assertTrue(output_path.exists())
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["source_artifacts"], ["decision.outputs", "portfolio.aggregation"])
            self.assertEqual([row["asset_id"] for row in payload["by_asset"]], ["AAPL", "MSFT"])
            self.assertEqual(entry["name"], "portfolio.comparison")
            self.assertTrue(entry["path"].startswith("artifacts/portfolio/"))
            self.assertAlmostEqual(payload["total_weight"], 1.0, places=12)
            self.assertAlmostEqual(payload["total_weighted_signal"], 0.56, places=12)

            compare_portfolio(run_id=run_id, base_path=str(base))
            updated = json.loads(manifest_path.read_text(encoding="utf-8"))
            entries = [e for e in updated["artifact_index"] if e["name"] == "portfolio.comparison"]
            self.assertEqual(len(entries), 1)


if __name__ == "__main__":
    unittest.main()
