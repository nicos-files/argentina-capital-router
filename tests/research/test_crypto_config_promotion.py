import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.research.crypto_config_promotion import (
    build_crypto_config_candidate,
    build_crypto_config_diff,
    create_crypto_config_promotion_proposal,
    load_crypto_promotion_inputs,
    select_crypto_experiment_config,
    validate_crypto_config_promotion,
)


class CryptoConfigPromotionTests(unittest.TestCase):
    def _current_config(self) -> dict:
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
                {
                    "symbol": "BTCUSDT",
                    "base": "BTC",
                    "quote": "USDT",
                    "exchange": "binance_spot",
                    "asset_class": "crypto",
                    "enabled": True,
                    "min_timeframe": "1m",
                    "strategy_enabled": False,
                    "paper_enabled": True,
                    "live_enabled": False,
                },
                {
                    "symbol": "ETHUSDT",
                    "base": "ETH",
                    "quote": "USDT",
                    "exchange": "binance_spot",
                    "asset_class": "crypto",
                    "enabled": True,
                    "min_timeframe": "1m",
                    "strategy_enabled": False,
                    "paper_enabled": True,
                    "live_enabled": False,
                },
            ],
        }

    def _results_payload(self) -> dict:
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
                    "warnings": ["Drawdown calculated from event-level equity points, not every candle."],
                    "metrics": {
                        "closed_trades_count": 12,
                        "open_trades_count": 1,
                        "expectancy": 0.22,
                        "profit_factor": 1.4,
                        "net_profit": 3.2,
                        "win_rate": 0.58,
                    },
                    "metadata": {"paper_only": True, "live_trading": False},
                },
                {
                    "config_id": "cfg-002",
                    "config": {
                        "name": "intraday_crypto_baseline",
                        "timeframe": "5m",
                        "lookback_limit": 120,
                        "fast_ma_window": 15,
                        "slow_ma_window": 50,
                        "min_abs_signal_strength": 0.001,
                        "max_volatility_pct": 0.08,
                        "risk_reward_ratio": 1.5,
                        "stop_loss_pct": 0.01,
                        "take_profit_pct": 0.008,
                        "max_paper_notional": 25.0,
                        "allow_short": False,
                    },
                    "symbols": ["BTCUSDT"],
                    "closed_trades_count": 3,
                    "open_trades_count": 0,
                    "net_profit": -1.0,
                    "expectancy": -0.1,
                    "profit_factor": 0.8,
                    "win_rate": 0.33,
                    "max_drawdown_pct": -25.0,
                    "total_fees": 0.8,
                    "total_slippage": 0.7,
                    "eligible": False,
                    "disqualification_reasons": ["closed_trades_below_min"],
                    "warnings": [],
                    "metrics": {
                        "closed_trades_count": 3,
                        "open_trades_count": 0,
                        "expectancy": -0.1,
                        "profit_factor": 0.8,
                        "net_profit": -1.0,
                        "win_rate": 0.33,
                    },
                    "metadata": {"paper_only": True, "live_trading": False},
                },
            ],
        }

    def _rankings(self) -> list[dict]:
        return [
            {
                "config_id": "cfg-001",
                "config": self._results_payload()["results"][0]["config"],
                "metrics": self._results_payload()["results"][0]["metrics"],
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
            },
            {
                "config_id": "cfg-002",
                "config": self._results_payload()["results"][1]["config"],
                "metrics": self._results_payload()["results"][1]["metrics"],
                "eligible": False,
                "closed_trades_count": 3,
                "open_trades_count": 0,
                "net_profit": -1.0,
                "expectancy": -0.1,
                "profit_factor": 0.8,
                "win_rate": 0.33,
                "max_drawdown_pct": -25.0,
                "total_fees": 0.8,
                "total_slippage": 0.7,
                "disqualification_reasons": ["closed_trades_below_min"],
                "warnings": [],
                "rank": 2,
            },
        ]

    def _write_inputs(self, root: Path) -> tuple[Path, Path]:
        experiment_dir = root / "experiments" / "crypto_baseline_grid_v1"
        experiment_dir.mkdir(parents=True, exist_ok=True)
        (experiment_dir / "crypto_paper_experiment_results.json").write_text(
            json.dumps(self._results_payload(), ensure_ascii=False),
            encoding="utf-8",
        )
        (experiment_dir / "crypto_paper_experiment_rankings.json").write_text(
            json.dumps(self._rankings(), ensure_ascii=False),
            encoding="utf-8",
        )
        config_path = root / "crypto.json"
        config_path.write_text(json.dumps(self._current_config(), ensure_ascii=False), encoding="utf-8")
        return experiment_dir, config_path

    def test_select_config_by_config_id(self):
        selected, method = select_crypto_experiment_config(
            results_payload=self._results_payload(),
            rankings=self._rankings(),
            config_id="cfg-001",
        )
        self.assertEqual(selected["config_id"], "cfg-001")
        self.assertEqual(method, "config_id")

    def test_select_best_eligible_config(self):
        selected, method = select_crypto_experiment_config(
            results_payload=self._results_payload(),
            rankings=self._rankings(),
            use_best_eligible=True,
        )
        self.assertEqual(selected["config_id"], "cfg-001")
        self.assertEqual(method, "best_eligible")

    def test_missing_config_id_fails_cleanly(self):
        with self.assertRaises(ValueError):
            select_crypto_experiment_config(
                results_payload=self._results_payload(),
                rankings=self._rankings(),
                config_id="cfg-999",
            )

    def test_missing_experiment_files_fail_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                load_crypto_promotion_inputs(
                    experiment_dir=Path(tmp) / "missing",
                    current_config_path=Path(tmp) / "crypto.json",
                )

    def test_candidate_updates_strategy_and_preserves_safety_defaults(self):
        candidate = build_crypto_config_candidate(
            current_config=self._current_config(),
            selected_result=self._results_payload()["results"][0],
            paper_forward_enable=False,
        )
        self.assertEqual(candidate["strategy"]["fast_ma_window"], 12)
        self.assertFalse(candidate["strategy"]["enabled"])
        self.assertFalse(candidate["strategy"]["allow_short"])
        self.assertTrue(all(not item["live_enabled"] for item in candidate["symbols"]))

    def test_paper_forward_enable_affects_candidate_only(self):
        current = self._current_config()
        before = json.dumps(current, sort_keys=True)
        candidate = build_crypto_config_candidate(
            current_config=current,
            selected_result=self._results_payload()["results"][0],
            paper_forward_enable=True,
        )
        self.assertTrue(candidate["strategy"]["enabled"])
        self.assertTrue(any(item["strategy_enabled"] for item in candidate["symbols"]))
        self.assertEqual(before, json.dumps(current, sort_keys=True))

    def test_diff_includes_changed_strategy_fields(self):
        current = self._current_config()
        candidate = build_crypto_config_candidate(
            current_config=current,
            selected_result=self._results_payload()["results"][0],
        )
        diff_payload = build_crypto_config_diff(current, candidate)
        changed_paths = {item["path"] for item in diff_payload["changed_fields"]}
        self.assertIn("strategy.fast_ma_window", changed_paths)

    def test_validation_warns_on_low_sample_negative_expectancy_and_profit_factor(self):
        current = self._current_config()
        selected = self._results_payload()["results"][1]
        candidate = build_crypto_config_candidate(current_config=current, selected_result=selected)
        diff_payload = build_crypto_config_diff(current, candidate)
        validation = validate_crypto_config_promotion(
            current_config=current,
            candidate_config=candidate,
            selected_result=selected,
            diff_payload=diff_payload,
        )
        self.assertIn("Small sample size: fewer than 30 closed trades.", validation["warnings"])
        self.assertIn("Non-positive expectancy in selected config.", validation["warnings"])
        self.assertIn("Profit factor is not above 1.0.", validation["warnings"])

    def test_validation_errors_on_invalid_fast_slow(self):
        current = self._current_config()
        selected = deepcopy(self._results_payload()["results"][0])
        selected["config"]["fast_ma_window"] = 30
        selected["config"]["slow_ma_window"] = 30
        candidate = build_crypto_config_candidate(current_config=current, selected_result=selected)
        diff_payload = build_crypto_config_diff(current, candidate)
        validation = validate_crypto_config_promotion(
            current_config=current,
            candidate_config=candidate,
            selected_result=selected,
            diff_payload=diff_payload,
        )
        self.assertIn("fast_ma_window_must_be_less_than_slow_ma_window", validation["errors"])

    def test_create_proposal_writes_markdown_and_json_without_modifying_production(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            experiment_dir, config_path = self._write_inputs(root)
            original = config_path.read_text(encoding="utf-8")
            output_dir = root / "promotions"
            candidate, diff_payload, validation, report_text, written = create_crypto_config_promotion_proposal(
                experiment_dir=experiment_dir,
                current_config_path=config_path,
                output_dir=output_dir,
                config_id="cfg-001",
            )
            self.assertTrue((output_dir / "crypto_config_candidate.json").exists())
            self.assertTrue((output_dir / "crypto_config_promotion_proposal.md").exists())
            json.loads((output_dir / "crypto_config_candidate.json").read_text(encoding="utf-8"))
            json.loads((output_dir / "crypto_config_diff.json").read_text(encoding="utf-8"))
            json.loads((output_dir / "crypto_config_promotion_validation.json").read_text(encoding="utf-8"))
            self.assertIn("# Crypto Config Promotion Proposal", report_text)
            self.assertTrue(written)
            self.assertEqual(original, config_path.read_text(encoding="utf-8"))
            self.assertFalse(validation["live_trading"])
            self.assertEqual(candidate["strategy"]["fast_ma_window"], 12)


if __name__ == "__main__":
    unittest.main()
