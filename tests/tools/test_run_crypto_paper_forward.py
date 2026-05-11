import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.tools.run_crypto_paper_forward import run_crypto_paper_forward_tool


class RunCryptoPaperForwardToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.prev_flag = os.getenv("ENABLE_CRYPTO_PAPER_FORWARD")

    def tearDown(self) -> None:
        if self.prev_flag is None:
            os.environ.pop("ENABLE_CRYPTO_PAPER_FORWARD", None)
        else:
            os.environ["ENABLE_CRYPTO_PAPER_FORWARD"] = self.prev_flag

    def _candidate_config(self) -> dict:
        return {
            "version": 1,
            "market": "crypto",
            "default_quote_currency": "USDT",
            "strategy": {
                "name": "intraday_crypto_baseline",
                "enabled": True,
                "timeframe": "5m",
                "lookback_limit": 120,
                "fast_ma_window": 2,
                "slow_ma_window": 3,
                "min_abs_signal_strength": 0.0001,
                "max_volatility_pct": 1.0,
                "risk_reward_ratio": 1.5,
                "stop_loss_pct": 0.02,
                "take_profit_pct": 0.01,
                "max_paper_notional": 25.0,
                "allow_short": False,
            },
            "symbols": [
                {
                    "symbol": "BTCUSDT",
                    "enabled": True,
                    "strategy_enabled": True,
                    "paper_enabled": True,
                    "live_enabled": False,
                }
            ],
        }

    def _prices_bundle(self) -> dict:
        return {
            "candles": {
                "BTCUSDT": [
                    {"timestamp": "2026-04-25T10:00:00Z", "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 10.0},
                    {"timestamp": "2026-04-25T10:05:00Z", "open": 100.0, "high": 101.5, "low": 99.9, "close": 101.0, "volume": 10.0},
                    {"timestamp": "2026-04-25T10:10:00Z", "open": 101.0, "high": 102.5, "low": 100.9, "close": 102.0, "volume": 11.0},
                    {"timestamp": "2026-04-25T10:15:00Z", "open": 102.0, "high": 103.5, "low": 101.8, "close": 103.0, "volume": 12.0},
                    {"timestamp": "2026-04-25T10:20:00Z", "open": 103.0, "high": 104.0, "low": 102.8, "close": 103.5, "volume": 12.0},
                ]
            }
        }

    def _write_inputs(self, root: Path) -> tuple[Path, Path]:
        candidate_path = root / "candidate.json"
        prices_path = root / "prices.json"
        candidate_path.write_text(json.dumps(self._candidate_config(), ensure_ascii=False), encoding="utf-8")
        prices_path.write_text(json.dumps(self._prices_bundle(), ensure_ascii=False), encoding="utf-8")
        return candidate_path, prices_path

    def test_tool_refuses_without_flag(self):
        os.environ.pop("ENABLE_CRYPTO_PAPER_FORWARD", None)
        with tempfile.TemporaryDirectory() as tmp:
            candidate_path, prices_path = self._write_inputs(Path(tmp))
            result = run_crypto_paper_forward_tool(
                candidate_config=str(candidate_path),
                artifacts_dir=str(Path(tmp) / "artifacts" / "crypto_paper"),
                prices_json=str(prices_path),
            )
            self.assertEqual(result["status"], "SKIPPED")

    def test_valid_candidate_runs_and_writes_forward_outputs(self):
        os.environ["ENABLE_CRYPTO_PAPER_FORWARD"] = "1"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate_path, prices_path = self._write_inputs(root)
            production_config = root / "config" / "market_universe" / "crypto.json"
            production_config.parent.mkdir(parents=True, exist_ok=True)
            production_config.write_text(json.dumps({"unchanged": True}), encoding="utf-8")
            artifacts_dir = root / "artifacts" / "crypto_paper"
            result = run_crypto_paper_forward_tool(
                candidate_config=str(candidate_path),
                artifacts_dir=str(artifacts_dir),
                prices_json=str(prices_path),
            )
            self.assertEqual(result["status"], "SUCCESS")
            self.assertTrue((artifacts_dir / "paper_forward" / "crypto_paper_forward_result.json").exists())
            self.assertTrue((artifacts_dir / "paper_forward" / "crypto_manual_trade_tickets.md").exists())
            self.assertEqual(production_config.read_text(encoding="utf-8"), json.dumps({"unchanged": True}))


if __name__ == "__main__":
    unittest.main()
