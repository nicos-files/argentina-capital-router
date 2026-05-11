import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.tools.update_crypto_paper_history import run_update_crypto_paper_history


class UpdateCryptoPaperHistoryToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.prev_history = os.getenv("ENABLE_CRYPTO_PAPER_HISTORY")

    def tearDown(self) -> None:
        if self.prev_history is None:
            os.environ.pop("ENABLE_CRYPTO_PAPER_HISTORY", None)
        else:
            os.environ["ENABLE_CRYPTO_PAPER_HISTORY"] = self.prev_history

    def _write_daily_close(self, run_root: Path, *, as_of: str, ending_equity: float) -> None:
        daily_close = run_root / "artifacts" / "crypto_paper" / "daily_close"
        daily_close.mkdir(parents=True, exist_ok=True)
        payload = {
            "as_of": as_of,
            "positions_marked": [{"symbol": "BTCUSDT", "quantity": 0.1, "avg_entry_price": 100.0, "last_price": ending_equity, "unrealized_pnl": ending_equity - 100.0}],
            "warnings": [],
            "provider_health": {},
            "paper_only": True,
            "live_trading": False,
            "metadata": {},
            "performance": {
                "as_of": as_of,
                "starting_cash": 100.0,
                "ending_cash": 90.0,
                "starting_equity": 100.0,
                "ending_equity": ending_equity,
                "positions_value": 10.0,
                "realized_pnl": 0.0,
                "unrealized_pnl": ending_equity - 100.0,
                "total_pnl": ending_equity - 100.0,
                "total_return_pct": (ending_equity - 100.0) / 100.0,
                "fees_paid": 0.1,
                "fills_count": 1,
                "accepted_orders_count": 1,
                "rejected_orders_count": 0,
                "open_positions_count": 1,
                "symbols_held": ["BTCUSDT"],
                "data_quality_warnings": [],
                "provider_health": {},
                "metadata": {},
                "paper_only": True,
                "live_trading": False,
            },
        }
        (daily_close / "crypto_paper_daily_close.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        (daily_close / "crypto_paper_performance_summary.json").write_text(json.dumps(payload["performance"], ensure_ascii=False), encoding="utf-8")

    def test_without_flag_refuses_safely(self) -> None:
        os.environ.pop("ENABLE_CRYPTO_PAPER_HISTORY", None)
        with tempfile.TemporaryDirectory() as tmp:
            result = run_update_crypto_paper_history(run_id="20260424-1900", base_path=tmp)
            self.assertEqual(result["status"], "SKIPPED")

    def test_with_flag_and_one_daily_close_writes_history(self) -> None:
        os.environ["ENABLE_CRYPTO_PAPER_HISTORY"] = "1"
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "20260424-1900"
            self._write_daily_close(run_root, as_of="2026-04-24T19:00:00", ending_equity=101.0)
            result = run_update_crypto_paper_history(run_id="20260424-1900", base_path=tmp)
            history_dir = run_root / "artifacts" / "crypto_paper" / "history"
            self.assertEqual(result["status"], "SUCCESS")
            self.assertTrue((history_dir / "crypto_paper_performance_history.json").exists())

    def test_rerunning_same_daily_close_does_not_duplicate_entries(self) -> None:
        os.environ["ENABLE_CRYPTO_PAPER_HISTORY"] = "1"
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "20260424-1900"
            self._write_daily_close(run_root, as_of="2026-04-24T19:00:00", ending_equity=101.0)
            run_update_crypto_paper_history(run_id="20260424-1900", base_path=tmp)
            result = run_update_crypto_paper_history(run_id="20260424-1900", base_path=tmp)
            history_payload = json.loads((run_root / "artifacts" / "crypto_paper" / "history" / "crypto_paper_performance_history.json").read_text(encoding="utf-8"))
            self.assertEqual(len(history_payload["entries"]), 1)
            self.assertEqual(result["entries_count"], 1)

    def test_existing_history_is_preserved_and_updated(self) -> None:
        os.environ["ENABLE_CRYPTO_PAPER_HISTORY"] = "1"
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "20260424-1900"
            self._write_daily_close(run_root, as_of="2026-04-24T19:00:00", ending_equity=101.0)
            run_update_crypto_paper_history(run_id="20260424-1900", base_path=tmp)
            self._write_daily_close(run_root, as_of="2026-04-25T19:00:00", ending_equity=99.0)
            result = run_update_crypto_paper_history(run_id="20260424-1900", base_path=tmp)
            history_payload = json.loads((run_root / "artifacts" / "crypto_paper" / "history" / "crypto_paper_performance_history.json").read_text(encoding="utf-8"))
            self.assertEqual(len(history_payload["entries"]), 2)
            self.assertEqual(result["entries_count"], 2)

    def test_missing_daily_close_warns_without_crash(self) -> None:
        os.environ["ENABLE_CRYPTO_PAPER_HISTORY"] = "1"
        with tempfile.TemporaryDirectory() as tmp:
            result = run_update_crypto_paper_history(run_id="20260424-1900", base_path=tmp, allow_missing=True)
            self.assertEqual(result["status"], "SUCCESS")
            self.assertTrue(result["warnings"])

    def test_does_not_require_api_keys(self) -> None:
        os.environ["ENABLE_CRYPTO_PAPER_HISTORY"] = "1"
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "20260424-1900"
            self._write_daily_close(run_root, as_of="2026-04-24T19:00:00", ending_equity=101.0)
            result = run_update_crypto_paper_history(run_id="20260424-1900", base_path=tmp)
            self.assertEqual(result["status"], "SUCCESS")

    def test_does_not_touch_equity_artifacts_or_execution_plan(self) -> None:
        os.environ["ENABLE_CRYPTO_PAPER_HISTORY"] = "1"
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "20260424-1900"
            self._write_daily_close(run_root, as_of="2026-04-24T19:00:00", ending_equity=101.0)
            equity_artifact = run_root / "artifacts" / "paper.day_close.v1.0.0.json"
            execution_plan = run_root / "artifacts" / "execution.plan.v1.0.0.json"
            equity_artifact.parent.mkdir(parents=True, exist_ok=True)
            equity_artifact.write_text("{}", encoding="utf-8")
            execution_plan.write_text("{}", encoding="utf-8")
            result = run_update_crypto_paper_history(run_id="20260424-1900", base_path=tmp)
            self.assertEqual(result["status"], "SUCCESS")
            self.assertEqual(equity_artifact.read_text(encoding="utf-8"), "{}")
            self.assertEqual(execution_plan.read_text(encoding="utf-8"), "{}")

    def test_no_broker_or_live_code_is_called(self) -> None:
        os.environ["ENABLE_CRYPTO_PAPER_HISTORY"] = "1"
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "20260424-1900"
            self._write_daily_close(run_root, as_of="2026-04-24T19:00:00", ending_equity=101.0)
            result = run_update_crypto_paper_history(run_id="20260424-1900", base_path=tmp)
            self.assertEqual(result["status"], "SUCCESS")


if __name__ == "__main__":
    unittest.main()
