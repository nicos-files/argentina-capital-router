import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.tools.run_crypto_paper_experiments import run_crypto_paper_experiments_tool


def _sample_config():
    return {
        "version": 1,
        "experiment_name": "crypto_baseline_grid_v1",
        "symbols": ["BTCUSDT"],
        "timeframe": "5m",
        "starting_cash": 100.0,
        "fee_bps": 10.0,
        "slippage_bps": 5.0,
        "max_paper_notional": 25.0,
        "allow_short": False,
        "ranking": {
            "primary_metric": "expectancy",
            "secondary_metrics": ["profit_factor", "net_profit", "max_drawdown_pct", "closed_trades_count"],
            "min_closed_trades": 1,
            "max_drawdown_pct": -20.0,
        },
        "grid": {
            "fast_ma_window": [2],
            "slow_ma_window": [3],
            "min_abs_signal_strength": [0.0001],
            "max_volatility_pct": [1.0],
            "stop_loss_pct": [0.02],
            "take_profit_pct": [0.01],
        },
    }


def _sample_candles():
    return {
        "BTCUSDT": [
            {"timestamp": "2026-04-01T00:00:00Z", "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 10.0},
            {"timestamp": "2026-04-01T00:05:00Z", "open": 100.0, "high": 101.5, "low": 99.9, "close": 101.0, "volume": 10.0},
            {"timestamp": "2026-04-01T00:10:00Z", "open": 101.0, "high": 102.5, "low": 100.9, "close": 102.0, "volume": 11.0},
            {"timestamp": "2026-04-01T00:15:00Z", "open": 102.0, "high": 103.5, "low": 101.8, "close": 103.0, "volume": 12.0},
            {"timestamp": "2026-04-01T00:20:00Z", "open": 103.0, "high": 105.0, "low": 102.4, "close": 104.0, "volume": 12.0},
        ]
    }


class RunCryptoPaperExperimentsToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.prev_flag = os.getenv("ENABLE_CRYPTO_PAPER_EXPERIMENTS")

    def tearDown(self) -> None:
        if self.prev_flag is None:
            os.environ.pop("ENABLE_CRYPTO_PAPER_EXPERIMENTS", None)
        else:
            os.environ["ENABLE_CRYPTO_PAPER_EXPERIMENTS"] = self.prev_flag

    def _write_inputs(self, root: Path, *, config=None, candles=None) -> tuple[Path, Path]:
        config_path = root / "experiment.json"
        candles_path = root / "candles.json"
        config_path.write_text(json.dumps(config or _sample_config(), ensure_ascii=False), encoding="utf-8")
        candles_path.write_text(json.dumps(candles or _sample_candles(), ensure_ascii=False), encoding="utf-8")
        return config_path, candles_path

    def test_without_flag_refuses_safely(self):
        os.environ.pop("ENABLE_CRYPTO_PAPER_EXPERIMENTS", None)
        with tempfile.TemporaryDirectory() as tmp:
            config_path, candles_path = self._write_inputs(Path(tmp))
            result = run_crypto_paper_experiments_tool(experiment_config=str(config_path), candles_json=str(candles_path))
            self.assertEqual(result["status"], "SKIPPED")

    def test_with_flag_and_sample_inputs_writes_artifacts(self):
        os.environ["ENABLE_CRYPTO_PAPER_EXPERIMENTS"] = "1"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path, candles_path = self._write_inputs(root)
            output_dir = root / "artifacts" / "crypto_paper" / "experiments" / "sample"
            result = run_crypto_paper_experiments_tool(
                experiment_config=str(config_path),
                candles_json=str(candles_path),
                output_dir=str(output_dir),
            )
            self.assertEqual(result["status"], "SUCCESS")
            self.assertTrue((output_dir / "crypto_paper_experiment_results.json").exists())

    def test_missing_candles_or_config_fails_cleanly(self):
        os.environ["ENABLE_CRYPTO_PAPER_EXPERIMENTS"] = "1"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "experiment.json"
            candles_path = root / "candles.json"
            config_path.write_text(json.dumps(_sample_config(), ensure_ascii=False), encoding="utf-8")
            missing_candles = run_crypto_paper_experiments_tool(experiment_config=str(config_path), candles_json=str(candles_path))
            missing_config = run_crypto_paper_experiments_tool(experiment_config=str(root / "missing.json"), candles_json=str(candles_path))
            self.assertEqual(missing_candles["status"], "FAILED")
            self.assertEqual(missing_config["status"], "FAILED")

    def test_too_large_grid_fails_cleanly(self):
        os.environ["ENABLE_CRYPTO_PAPER_EXPERIMENTS"] = "1"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            huge = _sample_config()
            huge["grid"]["fast_ma_window"] = [2, 3, 4, 5, 6]
            huge["grid"]["slow_ma_window"] = [7, 8, 9, 10, 11]
            huge["grid"]["take_profit_pct"] = [0.01, 0.02, 0.03]
            huge["grid"]["stop_loss_pct"] = [0.01, 0.02, 0.03]
            config_path, candles_path = self._write_inputs(root, config=huge)
            result = run_crypto_paper_experiments_tool(
                experiment_config=str(config_path),
                candles_json=str(candles_path),
                max_configs=10,
            )
            self.assertEqual(result["status"], "FAILED")

    def test_output_stays_under_crypto_paper_experiments_and_does_not_touch_other_artifacts(self):
        os.environ["ENABLE_CRYPTO_PAPER_EXPERIMENTS"] = "1"
        crypto_config = REPO_ROOT / "config" / "market_universe" / "crypto.json"
        before = crypto_config.read_text(encoding="utf-8") if crypto_config.exists() else None
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path, candles_path = self._write_inputs(root)
            equity_artifact = root / "artifacts" / "paper.day_close.v1.0.0.json"
            execution_plan = root / "artifacts" / "execution.plan.v1.0.0.json"
            equity_artifact.parent.mkdir(parents=True, exist_ok=True)
            equity_artifact.write_text("{}", encoding="utf-8")
            execution_plan.write_text("{}", encoding="utf-8")
            result = run_crypto_paper_experiments_tool(
                experiment_config=str(config_path),
                candles_json=str(candles_path),
            )
            self.assertEqual(result["status"], "SUCCESS")
            self.assertIn("artifacts\\crypto_paper\\experiments".lower(), result["output_dir"].lower().replace("/", "\\"))
            self.assertEqual(equity_artifact.read_text(encoding="utf-8"), "{}")
            self.assertEqual(execution_plan.read_text(encoding="utf-8"), "{}")
        after = crypto_config.read_text(encoding="utf-8") if crypto_config.exists() else None
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
