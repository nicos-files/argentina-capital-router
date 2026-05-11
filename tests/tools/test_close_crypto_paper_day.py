import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.execution.crypto_paper_models import (
    CryptoPaperExecutionResult,
    CryptoPaperFill,
    CryptoPaperOrder,
    CryptoPaperPortfolioSnapshot,
    CryptoPaperPosition,
)
from src.tools.close_crypto_paper_day import run_close_crypto_paper_day


class CloseCryptoPaperDayToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.prev_close = os.getenv("ENABLE_CRYPTO_PAPER_CLOSE")
        self.prev_market = os.getenv("ENABLE_CRYPTO_MARKET_DATA")
        self.as_of = datetime(2026, 4, 24, 19, 15, 0)

    def tearDown(self) -> None:
        if self.prev_close is None:
            os.environ.pop("ENABLE_CRYPTO_PAPER_CLOSE", None)
        else:
            os.environ["ENABLE_CRYPTO_PAPER_CLOSE"] = self.prev_close
        if self.prev_market is None:
            os.environ.pop("ENABLE_CRYPTO_MARKET_DATA", None)
        else:
            os.environ["ENABLE_CRYPTO_MARKET_DATA"] = self.prev_market

    def _write_run_artifacts(self, run_root: Path) -> None:
        artifacts = run_root / "artifacts" / "crypto_paper"
        artifacts.mkdir(parents=True, exist_ok=True)
        order = CryptoPaperOrder("o1", "BTCUSDT", "BUY", 10.0, None, 100.0, "PENDING", None, self.as_of, {"paper_only": True})
        fill = CryptoPaperFill("f1", "o1", "BTCUSDT", "BUY", 0.1, 100.5, 10.0, 0.1, 0.05, 10.1, self.as_of)
        position = CryptoPaperPosition("BTCUSDT", 0.1, 100.0, 0.0, 0.2, 102.0, self.as_of)
        snapshot = CryptoPaperPortfolioSnapshot(self.as_of, 89.9, 100.1, 10.2, 0.0, 0.2, 0.1, [position])
        result = CryptoPaperExecutionResult([order], [], [fill], snapshot)
        (artifacts / "crypto_paper_orders.json").write_text(json.dumps([order.to_dict()], ensure_ascii=False), encoding="utf-8")
        (artifacts / "crypto_paper_fills.json").write_text(json.dumps([fill.to_dict()], ensure_ascii=False), encoding="utf-8")
        (artifacts / "crypto_paper_positions.json").write_text(json.dumps([position.to_dict()], ensure_ascii=False), encoding="utf-8")
        (artifacts / "crypto_paper_snapshot.json").write_text(json.dumps(snapshot.to_dict(), ensure_ascii=False), encoding="utf-8")
        (artifacts / "crypto_paper_execution_result.json").write_text(json.dumps(result.to_dict(), ensure_ascii=False), encoding="utf-8")

    def test_without_enable_flag_refuses_safely(self) -> None:
        os.environ.pop("ENABLE_CRYPTO_PAPER_CLOSE", None)
        with tempfile.TemporaryDirectory() as tmp:
            result = run_close_crypto_paper_day(run_id="20260424-1915", base_path=tmp)
            self.assertEqual(result["status"], "SKIPPED")

    def test_with_flag_and_prices_json_runs_without_network(self) -> None:
        os.environ["ENABLE_CRYPTO_PAPER_CLOSE"] = "1"
        os.environ.pop("ENABLE_CRYPTO_MARKET_DATA", None)
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "20260424-1915"
            self._write_run_artifacts(run_root)
            prices_path = Path(tmp) / "prices.json"
            prices_path.write_text(json.dumps({"BTCUSDT": 105.0}), encoding="utf-8")
            provider = Mock()
            result = run_close_crypto_paper_day(
                run_id="20260424-1915",
                base_path=tmp,
                prices_json=str(prices_path),
                as_of="2026-04-24T19:15:00",
                provider=provider,
            )
            self.assertEqual(result["status"], "SUCCESS")
            provider.health_check.assert_not_called()

    def test_writes_daily_close_artifacts(self) -> None:
        os.environ["ENABLE_CRYPTO_PAPER_CLOSE"] = "1"
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "20260424-1915"
            self._write_run_artifacts(run_root)
            prices_path = Path(tmp) / "prices.json"
            prices_path.write_text(json.dumps({"BTCUSDT": 105.0}), encoding="utf-8")
            result = run_close_crypto_paper_day(
                run_id="20260424-1915",
                base_path=tmp,
                prices_json=str(prices_path),
            )
            self.assertTrue((run_root / "artifacts" / "crypto_paper" / "daily_close" / "crypto_paper_daily_close.json").exists())
            self.assertEqual(result["status"], "SUCCESS")

    def test_does_not_require_api_keys(self) -> None:
        os.environ["ENABLE_CRYPTO_PAPER_CLOSE"] = "1"
        os.environ.pop("ENABLE_CRYPTO_MARKET_DATA", None)
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "20260424-1915"
            self._write_run_artifacts(run_root)
            prices_path = Path(tmp) / "prices.json"
            prices_path.write_text(json.dumps({"BTCUSDT": 101.0}), encoding="utf-8")
            result = run_close_crypto_paper_day(
                run_id="20260424-1915",
                base_path=tmp,
                prices_json=str(prices_path),
            )
            self.assertEqual(result["status"], "SUCCESS")

    def test_no_live_or_broker_code_is_called(self) -> None:
        os.environ["ENABLE_CRYPTO_PAPER_CLOSE"] = "1"
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "20260424-1915"
            self._write_run_artifacts(run_root)
            provider = Mock()
            provider.health_check.return_value = Mock(
                provider_name="binance_spot",
                status="healthy",
                message="ok",
                checked_at_utc="2026-04-24T19:15:00",
            )
            provider.get_latest_quote.return_value = {"last_price": 103.0}
            os.environ["ENABLE_CRYPTO_MARKET_DATA"] = "1"
            result = run_close_crypto_paper_day(
                run_id="20260424-1915",
                base_path=tmp,
                provider=provider,
            )
            self.assertEqual(result["status"], "SUCCESS")
            provider.get_latest_quote.assert_called()


if __name__ == "__main__":
    unittest.main()
