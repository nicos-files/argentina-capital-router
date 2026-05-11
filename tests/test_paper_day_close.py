import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.tools.close_paper_day import close_paper_day


class PaperDayCloseTests(unittest.TestCase):
    def test_close_paper_day_writes_summary(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_id = "20260101-0930"
            run_root = root / "runs" / run_id
            (run_root / "artifacts").mkdir(parents=True, exist_ok=True)
            (run_root / "manifests").mkdir(parents=True, exist_ok=True)

            (run_root / "manifests" / "run_manifest.v1.0.0.json").write_text(
                json.dumps({"artifact_index": [], "schema_version": "1.0.0", "reader_min_version": "1.0.0", "run_id": run_id}),
                encoding="utf-8",
            )
            (run_root / "artifacts" / "recommendation.outputs.v1.0.0.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1.0.0",
                        "reader_min_version": "1.0.0",
                        "run_id": run_id,
                        "execution_date": "2026-01-01",
                        "recommendations": [{"asset_id": "AAA", "price_used": 10.0}],
                    }
                ),
                encoding="utf-8",
            )
            (run_root / "artifacts" / "execution.results.v1.0.0.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1.0.0",
                        "reader_min_version": "1.0.0",
                        "run_id": run_id,
                        "results": [{"fees_actual": 2.0}],
                    }
                ),
                encoding="utf-8",
            )
            (run_root / "artifacts" / "positions_snapshot_before.json").write_text(
                json.dumps({"positions": [], "cash": {"USD": 100.0}, "cash_by_broker": {}}),
                encoding="utf-8",
            )
            (run_root / "artifacts" / "positions_snapshot_after.json").write_text(
                json.dumps(
                    {
                        "positions": [{"asset_id": "AAA", "broker": "iol", "qty": 9.8, "avg_price": 10.0, "currency": "USD"}],
                        "cash": {"USD": 0.0},
                        "cash_by_broker": {},
                    }
                ),
                encoding="utf-8",
            )

            old_root = None
            import src.tools.close_paper_day as module

            old_root = module.ROOT
            module.ROOT = root
            try:
                path = close_paper_day(run_id=run_id, base_path=str(root / "runs"), mark_date="2026-01-01")
            finally:
                module.ROOT = old_root

            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertAlmostEqual(float(payload["equity_before_usd"]), 100.0, places=6)
            self.assertAlmostEqual(float(payload["equity_after_usd"]), 98.0, places=6)
            self.assertAlmostEqual(float(payload["fees_total_usd"]), 2.0, places=6)
            self.assertAlmostEqual(float(payload["net_pnl_usd"]), -2.0, places=6)


if __name__ == "__main__":
    unittest.main()
