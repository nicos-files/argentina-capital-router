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

from src.tools.run_crypto_paper import run_crypto_paper


def _bullish_candles():
    closes = [100.0 + (i * 0.2) for i in range(40)]
    return pd.DataFrame({"date": pd.date_range("2026-04-24 10:00:00", periods=len(closes), freq="5min"), "close": closes, "volume": [10.0] * len(closes)})


class IntradayCryptoPaperExecutionWiringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.prev_market = os.getenv("ENABLE_CRYPTO_MARKET_DATA")
        self.prev_exec = os.getenv("ENABLE_CRYPTO_PAPER_EXECUTION")

    def tearDown(self) -> None:
        if self.prev_market is None:
            os.environ.pop("ENABLE_CRYPTO_MARKET_DATA", None)
        else:
            os.environ["ENABLE_CRYPTO_MARKET_DATA"] = self.prev_market
        if self.prev_exec is None:
            os.environ.pop("ENABLE_CRYPTO_PAPER_EXECUTION", None)
        else:
            os.environ["ENABLE_CRYPTO_PAPER_EXECUTION"] = self.prev_exec

    def test_execution_absent_flag_skips_executor(self) -> None:
        os.environ.pop("ENABLE_CRYPTO_PAPER_EXECUTION", None)
        os.environ["ENABLE_CRYPTO_MARKET_DATA"] = "1"
        result = run_crypto_paper(run_id="20260424-1200")
        self.assertEqual(result["status"], "SKIPPED")

    def test_enabled_but_no_recommendations_produces_no_fills(self) -> None:
        os.environ["ENABLE_CRYPTO_PAPER_EXECUTION"] = "1"
        os.environ["ENABLE_CRYPTO_MARKET_DATA"] = "1"
        provider = Mock()
        provider.provider_name = "binance_spot"
        provider.health_check.return_value = Mock(status="healthy", message="ok", checked_at_utc="2026-04-24T12:00:00")
        provider.get_historical_bars.return_value = pd.DataFrame()
        provider.get_latest_quote.return_value = {"last_price": 100.0}
        with tempfile.TemporaryDirectory() as tmp:
            result = run_crypto_paper(run_id="20260424-1200", base_path=tmp, provider=provider, as_of=datetime(2026, 4, 24, 12, 0, 0))
            self.assertEqual(result["fill_count"], 0)

    def test_enabled_strategy_with_mocked_buy_signal_creates_fill(self) -> None:
        os.environ["ENABLE_CRYPTO_PAPER_EXECUTION"] = "1"
        os.environ["ENABLE_CRYPTO_MARKET_DATA"] = "1"
        provider = Mock()
        provider.provider_name = "binance_spot"
        provider.health_check.return_value = Mock(status="healthy", message="ok", checked_at_utc="2026-04-24T12:00:00")
        provider.get_historical_bars.return_value = _bullish_candles()
        provider.get_latest_quote.return_value = {"last_price": 107.8, "ask": 107.8}
        config_path = REPO_ROOT / "config" / "market_universe" / "crypto.json"
        original = json.loads(config_path.read_text(encoding="utf-8"))
        modified = dict(original)
        modified["strategy"] = {**dict(original.get("strategy") or {}), "enabled": True}
        modified["symbols"] = [
            {**symbol, "strategy_enabled": True if symbol["symbol"] == "BTCUSDT" else False}
            for symbol in original["symbols"]
        ]
        try:
            config_path.write_text(json.dumps(modified, ensure_ascii=False), encoding="utf-8")
            with tempfile.TemporaryDirectory() as tmp:
                result = run_crypto_paper(run_id="20260424-1200", base_path=tmp, provider=provider, as_of=datetime(2026, 4, 24, 12, 0, 0))
                self.assertEqual(result["status"], "SUCCESS")
                self.assertEqual(result["fill_count"], 1)
                artifact_root = Path(tmp) / "20260424-1200" / "artifacts" / "crypto_paper"
                self.assertTrue((artifact_root / "crypto_paper_fills.json").exists())
                self.assertFalse((Path(tmp) / "20260424-1200" / "artifacts" / "execution.plan.v1.0.0.json").exists())
        finally:
            config_path.write_text(json.dumps(original, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
