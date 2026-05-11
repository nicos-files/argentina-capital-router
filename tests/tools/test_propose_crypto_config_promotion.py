import json
import os
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.tools.propose_crypto_config_promotion import run_propose_crypto_config_promotion


def _current_config() -> dict:
    return {
        "version": 1,
        "market": "crypto",
        "default_quote_currency": "USDT",
        "strategy": {
            "name": "intraday_crypto_baseline",
            "enabled": False,
            "timeframe": "5m",
            "lookback_limit": 120,
            "fast_ma_window": 9,
            "slow_ma_window": 21,
            "min_abs_signal_strength": 0.001,
            "max_volatility_pct": 0.08,
            "risk_reward_ratio": 1.5,
            "stop_loss_pct": 0.006,
            "take_profit_pct": 0.009,
            "max_paper_notional": 25.0,
            "allow_short": False,
        },
        "symbols": [
            {"symbol": "BTCUSDT", "enabled": True, "strategy_enabled": False, "paper_enabled": True, "live_enabled": False},
            {"symbol": "ETHUSDT", "enabled": True, "strategy_enabled": False, "paper_enabled": True, "live_enabled": False},
        ],
    }


def _results_payload() -> dict:
    return {
        "summary": {"experiment_name": "crypto_baseline_grid_v1"},
        "results": [
            {
                "config_id": "cfg-001",
                "config": {
                    "name": "intraday_crypto_baseline",
                    "timeframe": "5m",
                    "lookback_limit": 120,
                    "fast_ma_window": 12,
                    "slow_ma_window": 30,
                    "min_abs_signal_strength": 0.002,
                    "max_volatility_pct": 0.04,
                    "risk_reward_ratio": 1.5,
                    "stop_loss_pct": 0.004,
                    "take_profit_pct": 0.012,
                    "max_paper_notional": 20.0,
                    "allow_short": False,
                },
                "symbols": ["BTCUSDT", "ETHUSDT"],
                "closed_trades_count": 12,
                "open_trades_count": 1,
                "net_profit": 3.2,
                "expectancy": 0.22,
                "profit_factor": 1.4,
                "win_rate": 0.58,
                "max_drawdown_pct": -8.0,
                "total_fees": 0.5,
                "total_slippage": 0.4,
                "eligible": True,
                "disqualification_reasons": [],
                "warnings": [],
                "metrics": {
                    "closed_trades_count": 12,
                    "open_trades_count": 1,
                    "expectancy": 0.22,
                    "profit_factor": 1.4,
                    "net_profit": 3.2,
                    "win_rate": 0.58,
                },
                "metadata": {"paper_only": True, "live_trading": False},
            }
        ],
    }


def _rankings() -> list[dict]:
    return [
        {
            "config_id": "cfg-001",
            "config": _results_payload()["results"][0]["config"],
            "metrics": _results_payload()["results"][0]["metrics"],
            "eligible": True,
            "closed_trades_count": 12,
            "open_trades_count": 1,
            "net_profit": 3.2,
            "expectancy": 0.22,
            "profit_factor": 1.4,
            "win_rate": 0.58,
            "max_drawdown_pct": -8.0,
            "total_fees": 0.5,
            "total_slippage": 0.4,
            "disqualification_reasons": [],
            "warnings": [],
            "rank": 1,
        }
    ]


class ProposeCryptoConfigPromotionToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.prev_flag = os.getenv("ENABLE_CRYPTO_CONFIG_PROMOTION_PROPOSAL")

    def tearDown(self) -> None:
        if self.prev_flag is None:
            os.environ.pop("ENABLE_CRYPTO_CONFIG_PROMOTION_PROPOSAL", None)
        else:
            os.environ["ENABLE_CRYPTO_CONFIG_PROMOTION_PROPOSAL"] = self.prev_flag

    def _write_inputs(self, root: Path) -> tuple[Path, Path]:
        experiment_dir = root / "artifacts" / "crypto_paper" / "experiments" / "crypto_baseline_grid_v1"
        experiment_dir.mkdir(parents=True, exist_ok=True)
        (experiment_dir / "crypto_paper_experiment_results.json").write_text(
            json.dumps(_results_payload(), ensure_ascii=False),
            encoding="utf-8",
        )
        (experiment_dir / "crypto_paper_experiment_rankings.json").write_text(
            json.dumps(_rankings(), ensure_ascii=False),
            encoding="utf-8",
        )
        config_path = root / "config" / "market_universe" / "crypto.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(_current_config(), ensure_ascii=False), encoding="utf-8")
        return experiment_dir, config_path

    def test_without_flag_refuses_safely(self):
        os.environ.pop("ENABLE_CRYPTO_CONFIG_PROMOTION_PROPOSAL", None)
        with tempfile.TemporaryDirectory() as tmp:
            experiment_dir, config_path = self._write_inputs(Path(tmp))
            result = run_propose_crypto_config_promotion(
                experiment_dir=str(experiment_dir),
                current_config=str(config_path),
                config_id="cfg-001",
            )
            self.assertEqual(result["status"], "SKIPPED")

    def test_with_flag_and_config_id_writes_candidate_artifacts(self):
        os.environ["ENABLE_CRYPTO_CONFIG_PROMOTION_PROPOSAL"] = "1"
        with tempfile.TemporaryDirectory() as tmp:
            experiment_dir, config_path = self._write_inputs(Path(tmp))
            output_dir = Path(tmp) / "artifacts" / "crypto_paper" / "config_promotions" / "crypto_baseline_grid_v1"
            result = run_propose_crypto_config_promotion(
                experiment_dir=str(experiment_dir),
                current_config=str(config_path),
                output_dir=str(output_dir),
                config_id="cfg-001",
            )
            self.assertEqual(result["status"], "SUCCESS")
            self.assertTrue((output_dir / "crypto_config_candidate.json").exists())

    def test_with_flag_and_use_best_eligible_writes_candidate_artifacts(self):
        os.environ["ENABLE_CRYPTO_CONFIG_PROMOTION_PROPOSAL"] = "1"
        with tempfile.TemporaryDirectory() as tmp:
            experiment_dir, config_path = self._write_inputs(Path(tmp))
            result = run_propose_crypto_config_promotion(
                experiment_dir=str(experiment_dir),
                current_config=str(config_path),
                use_best_eligible=True,
            )
            self.assertEqual(result["status"], "SUCCESS")

    def test_missing_required_selector_fails_cleanly(self):
        os.environ["ENABLE_CRYPTO_CONFIG_PROMOTION_PROPOSAL"] = "1"
        with tempfile.TemporaryDirectory() as tmp:
            experiment_dir, config_path = self._write_inputs(Path(tmp))
            result = run_propose_crypto_config_promotion(
                experiment_dir=str(experiment_dir),
                current_config=str(config_path),
            )
            self.assertEqual(result["status"], "FAILED")

    def test_paper_forward_enable_affects_candidate_only_and_output_is_isolated(self):
        os.environ["ENABLE_CRYPTO_CONFIG_PROMOTION_PROPOSAL"] = "1"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            experiment_dir, config_path = self._write_inputs(root)
            before = config_path.read_text(encoding="utf-8")
            equity_artifact = root / "artifacts" / "paper.day_close.v1.0.0.json"
            execution_plan = root / "artifacts" / "execution.plan.v1.0.0.json"
            equity_artifact.parent.mkdir(parents=True, exist_ok=True)
            equity_artifact.write_text("{}", encoding="utf-8")
            execution_plan.write_text("{}", encoding="utf-8")
            result = run_propose_crypto_config_promotion(
                experiment_dir=str(experiment_dir),
                current_config=str(config_path),
                use_best_eligible=True,
                paper_forward_enable=True,
            )
            self.assertEqual(result["status"], "SUCCESS")
            self.assertIn("config_promotions", result["output_dir"])
            candidate = json.loads(Path(result["artifacts"]["crypto_config_candidate.json"]).read_text(encoding="utf-8"))
            self.assertTrue(candidate["strategy"]["enabled"])
            self.assertEqual(before, config_path.read_text(encoding="utf-8"))
            self.assertEqual(equity_artifact.read_text(encoding="utf-8"), "{}")
            self.assertEqual(execution_plan.read_text(encoding="utf-8"), "{}")


if __name__ == "__main__":
    unittest.main()
