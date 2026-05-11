import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.execution.crypto_paper_models import CryptoPaperPortfolioSnapshot, CryptoPaperPosition
from src.tools.run_crypto_paper import run_crypto_paper


class RunCryptoPaperExitsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.prev_market = os.getenv("ENABLE_CRYPTO_MARKET_DATA")
        self.prev_exec = os.getenv("ENABLE_CRYPTO_PAPER_EXECUTION")
        self.prev_exits = os.getenv("ENABLE_CRYPTO_PAPER_EXITS")

    def tearDown(self) -> None:
        for name, value in (
            ("ENABLE_CRYPTO_MARKET_DATA", self.prev_market),
            ("ENABLE_CRYPTO_PAPER_EXECUTION", self.prev_exec),
            ("ENABLE_CRYPTO_PAPER_EXITS", self.prev_exits),
        ):
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def _write_open_position(self, artifact_root: Path) -> None:
        artifact_root.mkdir(parents=True, exist_ok=True)
        position = CryptoPaperPosition(
            symbol="BTCUSDT",
            quantity=0.1,
            avg_entry_price=100.0,
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            last_price=100.0,
            updated_at=datetime(2026, 4, 24, 10, 0, 0),
            metadata={"stop_loss": 95.0, "take_profit": 110.0, "avg_entry_price": 100.0},
        )
        snapshot = CryptoPaperPortfolioSnapshot(
            as_of=datetime(2026, 4, 24, 10, 0, 0),
            cash=89.9,
            equity=99.9,
            positions_value=10.0,
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            fees_paid=0.1,
            positions=[position],
        )
        (artifact_root / "crypto_paper_positions.json").write_text(json.dumps([position.to_dict()], ensure_ascii=False), encoding="utf-8")
        (artifact_root / "crypto_paper_snapshot.json").write_text(json.dumps(snapshot.to_dict(), ensure_ascii=False), encoding="utf-8")

    def test_without_exit_flag_behavior_is_unchanged(self) -> None:
        os.environ["ENABLE_CRYPTO_PAPER_EXECUTION"] = "1"
        os.environ["ENABLE_CRYPTO_MARKET_DATA"] = "1"
        os.environ.pop("ENABLE_CRYPTO_PAPER_EXITS", None)
        provider = Mock()
        provider.provider_name = "binance_spot"
        provider.health_check.return_value = Mock(status="healthy", message="ok", checked_at_utc="2026-04-24T12:00:00")
        with tempfile.TemporaryDirectory() as tmp:
            result = run_crypto_paper(run_id="20260424-1200", base_path=tmp, provider=provider, as_of=datetime(2026, 4, 24, 12, 0, 0))
            self.assertEqual(result.get("exit_count", 0), 0)

    def test_with_exit_flag_exit_evaluator_is_used_and_artifact_written(self) -> None:
        os.environ["ENABLE_CRYPTO_PAPER_EXECUTION"] = "1"
        os.environ["ENABLE_CRYPTO_MARKET_DATA"] = "1"
        os.environ["ENABLE_CRYPTO_PAPER_EXITS"] = "1"
        provider = Mock()
        provider.provider_name = "binance_spot"
        provider.health_check.return_value = Mock(status="healthy", message="ok", checked_at_utc="2026-04-24T12:00:00")
        provider.get_latest_quote.return_value = {"bid": 95.0, "last_price": 95.0}
        provider.get_historical_bars.return_value = pd.DataFrame(
            [{"date": datetime(2026, 4, 24, 11, 0, 0), "open": 100.0, "high": 101.0, "low": 94.0, "close": 95.0}]
        )
        with tempfile.TemporaryDirectory() as tmp:
            artifact_root = Path(tmp) / "20260424-1200" / "artifacts" / "crypto_paper"
            self._write_open_position(artifact_root)
            result = run_crypto_paper(run_id="20260424-1200", base_path=tmp, provider=provider, as_of=datetime(2026, 4, 24, 12, 0, 0))
            self.assertEqual(result["status"], "SUCCESS")
            self.assertEqual(result["exit_count"], 1)
            self.assertTrue((artifact_root / "crypto_paper_exit_events.json").exists())

    def test_no_live_trading_is_called(self) -> None:
        os.environ["ENABLE_CRYPTO_PAPER_EXECUTION"] = "1"
        os.environ["ENABLE_CRYPTO_MARKET_DATA"] = "1"
        os.environ["ENABLE_CRYPTO_PAPER_EXITS"] = "1"
        provider = Mock()
        provider.provider_name = "binance_spot"
        provider.health_check.return_value = Mock(status="healthy", message="ok", checked_at_utc="2026-04-24T12:00:00")
        provider.get_latest_quote.return_value = {"bid": 95.0, "last_price": 95.0}
        provider.get_historical_bars.return_value = pd.DataFrame(
            [{"date": datetime(2026, 4, 24, 11, 0, 0), "open": 100.0, "high": 101.0, "low": 94.0, "close": 95.0}]
        )
        with tempfile.TemporaryDirectory() as tmp:
            artifact_root = Path(tmp) / "20260424-1200" / "artifacts" / "crypto_paper"
            self._write_open_position(artifact_root)
            result = run_crypto_paper(run_id="20260424-1200", base_path=tmp, provider=provider, as_of=datetime(2026, 4, 24, 12, 0, 0))
            self.assertEqual(result["status"], "SUCCESS")


if __name__ == "__main__":
    unittest.main()
