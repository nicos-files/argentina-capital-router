import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.research.crypto_paper_experiments import (
    expand_crypto_paper_parameter_grid,
    load_crypto_paper_experiment_candles,
    run_crypto_paper_experiments,
)


def _ts(day: int, hour: int, minute: int = 0) -> str:
    return f"2026-04-{day:02d}T{hour:02d}:{minute:02d}:00Z"


class CryptoPaperExperimentsTests(unittest.TestCase):
    def _experiment_config(self, **overrides):
        base = {
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
        for key, value in overrides.items():
            if key == "grid":
                merged = dict(base["grid"])
                merged.update(value)
                base["grid"] = merged
            elif key == "ranking":
                merged = dict(base["ranking"])
                merged.update(value)
                base["ranking"] = merged
            else:
                base[key] = value
        return base

    def _bullish_take_profit_candles(self):
        return {
            "BTCUSDT": [
                {"timestamp": _ts(1, 0), "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 10.0},
                {"timestamp": _ts(1, 0, 5), "open": 100.0, "high": 101.5, "low": 99.9, "close": 101.0, "volume": 10.0},
                {"timestamp": _ts(1, 0, 10), "open": 101.0, "high": 102.5, "low": 100.9, "close": 102.0, "volume": 11.0},
                {"timestamp": _ts(1, 0, 15), "open": 102.0, "high": 103.5, "low": 101.8, "close": 103.0, "volume": 12.0},
                {"timestamp": _ts(1, 0, 20), "open": 103.0, "high": 105.0, "low": 102.4, "close": 104.0, "volume": 12.0},
            ]
        }

    def _stop_loss_candles(self):
        return {
            "BTCUSDT": [
                {"timestamp": _ts(1, 0), "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 10.0},
                {"timestamp": _ts(1, 0, 5), "open": 100.0, "high": 101.5, "low": 99.9, "close": 101.0, "volume": 10.0},
                {"timestamp": _ts(1, 0, 10), "open": 101.0, "high": 102.5, "low": 100.9, "close": 102.0, "volume": 11.0},
                {"timestamp": _ts(1, 0, 15), "open": 102.0, "high": 103.5, "low": 101.8, "close": 103.0, "volume": 12.0},
                {"timestamp": _ts(1, 0, 20), "open": 103.0, "high": 103.2, "low": 100.0, "close": 101.0, "volume": 12.0},
            ]
        }

    def _flat_candles(self):
        return {
            "BTCUSDT": [
                {"timestamp": _ts(1, 0), "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 10.0},
                {"timestamp": _ts(1, 0, 5), "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 10.0},
                {"timestamp": _ts(1, 0, 10), "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 10.0},
                {"timestamp": _ts(1, 0, 15), "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 10.0},
                {"timestamp": _ts(1, 0, 20), "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0, "volume": 10.0},
            ]
        }

    def _no_overlap_candles(self):
        return {
            "BTCUSDT": [
                {"timestamp": _ts(1, 0), "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 10.0},
                {"timestamp": _ts(1, 0, 5), "open": 100.0, "high": 101.5, "low": 99.9, "close": 101.0, "volume": 10.0},
                {"timestamp": _ts(1, 0, 10), "open": 101.0, "high": 102.5, "low": 100.9, "close": 102.0, "volume": 11.0},
                {"timestamp": _ts(1, 0, 15), "open": 102.0, "high": 103.5, "low": 101.8, "close": 103.0, "volume": 12.0},
                {"timestamp": _ts(1, 0, 20), "open": 103.0, "high": 103.8, "low": 102.9, "close": 103.5, "volume": 12.0},
                {"timestamp": _ts(1, 0, 25), "open": 103.5, "high": 103.9, "low": 103.2, "close": 103.6, "volume": 12.0},
            ]
        }

    def test_parameter_grid_expands_correctly(self):
        config = self._experiment_config(
            grid={
                "fast_ma_window": [2, 3],
                "slow_ma_window": [4, 5],
                "min_abs_signal_strength": [0.0001],
                "max_volatility_pct": [1.0],
                "stop_loss_pct": [0.01],
                "take_profit_pct": [0.02, 0.03],
            }
        )
        grid = expand_crypto_paper_parameter_grid(config)
        self.assertEqual(len(grid), 8)

    def test_grid_safety_limit_rejects_too_many_configs(self):
        config = self._experiment_config(
            grid={
                "fast_ma_window": [2, 3, 4, 5, 6],
                "slow_ma_window": [7, 8, 9, 10, 11],
                "min_abs_signal_strength": [0.0001, 0.0002, 0.0003],
                "max_volatility_pct": [0.5, 1.0],
                "stop_loss_pct": [0.01, 0.02],
                "take_profit_pct": [0.01, 0.02],
            }
        )
        with self.assertRaises(ValueError):
            expand_crypto_paper_parameter_grid(config, max_configs=20)

    def test_invalid_fast_slow_config_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary, rankings, _ = run_crypto_paper_experiments(
                experiment_config=self._experiment_config(grid={"fast_ma_window": [3], "slow_ma_window": [3]}),
                candles_by_symbol=self._bullish_take_profit_candles(),
                output_dir=Path(tmp),
            )
            self.assertEqual(summary["configs_tested"], 1)
            self.assertFalse(rankings[0]["eligible"])
            self.assertIn("fast_ma_window_must_be_less_than_slow_ma_window", rankings[0]["disqualification_reasons"])

    def test_historical_candles_are_loaded_and_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "candles.json"
            path.write_text(
                json.dumps(
                    {
                        "BTCUSDT": [
                            {"timestamp": _ts(1, 0, 10), "open": 101, "high": 102, "low": 100, "close": 101, "volume": 1},
                            {"timestamp": _ts(1, 0, 0), "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            candles = load_crypto_paper_experiment_candles(path)
            self.assertLess(candles["BTCUSDT"][0]["timestamp"], candles["BTCUSDT"][1]["timestamp"])

    def test_simulation_uses_only_past_candles(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary, rankings, _ = run_crypto_paper_experiments(
                experiment_config=self._experiment_config(),
                candles_by_symbol=self._bullish_take_profit_candles(),
                output_dir=Path(tmp),
            )
            best = rankings[0]
            closed = best["trade_log"]["closed_trades"]
            self.assertEqual(summary["best_config_id"], best["config_id"])
            self.assertTrue(closed)
            self.assertGreaterEqual(closed[0]["entry_time"], _ts(1, 0, 15).replace("Z", "+00:00"))

    def test_bullish_fixture_produces_buy_and_exit_trade(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, rankings, _ = run_crypto_paper_experiments(
                experiment_config=self._experiment_config(),
                candles_by_symbol=self._bullish_take_profit_candles(),
                output_dir=Path(tmp),
            )
            best = rankings[0]
            self.assertEqual(best["closed_trades_count"], 1)
            self.assertEqual(best["trade_log"]["closed_trades"][0]["result"], "WIN")

    def test_flat_fixture_produces_no_trades_and_low_quality_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, rankings, _ = run_crypto_paper_experiments(
                experiment_config=self._experiment_config(),
                candles_by_symbol=self._flat_candles(),
                output_dir=Path(tmp),
            )
            result = rankings[0]
            self.assertEqual(result["closed_trades_count"], 0)
            self.assertIn("closed_trades_below_min", result["disqualification_reasons"])

    def test_insufficient_cash_produces_rejected_order_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, rankings, _ = run_crypto_paper_experiments(
                experiment_config=self._experiment_config(starting_cash=5.0, max_paper_notional=25.0),
                candles_by_symbol=self._bullish_take_profit_candles(),
                output_dir=Path(tmp),
            )
            self.assertGreater(rankings[0]["metadata"]["rejected_orders_count"], 0)

    def test_no_overlapping_positions_are_opened_for_same_symbol(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, rankings, _ = run_crypto_paper_experiments(
                experiment_config=self._experiment_config(grid={"take_profit_pct": [0.20]}),
                candles_by_symbol=self._no_overlap_candles(),
                output_dir=Path(tmp),
            )
            result = rankings[0]
            self.assertEqual(result["open_trades_count"], 1)
            self.assertEqual(len(result["trade_log"]["open_trades"]), 1)

    def test_stop_loss_exit_is_simulated(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, rankings, _ = run_crypto_paper_experiments(
                experiment_config=self._experiment_config(grid={"stop_loss_pct": [0.01], "take_profit_pct": [0.10]}),
                candles_by_symbol=self._stop_loss_candles(),
                output_dir=Path(tmp),
            )
            result = rankings[0]
            self.assertEqual(result["trade_log"]["closed_trades"][0]["exit_reason"], "STOP_LOSS")

    def test_take_profit_exit_is_simulated(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, rankings, _ = run_crypto_paper_experiments(
                experiment_config=self._experiment_config(),
                candles_by_symbol=self._bullish_take_profit_candles(),
                output_dir=Path(tmp),
            )
            result = rankings[0]
            self.assertEqual(result["trade_log"]["closed_trades"][0]["exit_reason"], "TAKE_PROFIT")

    def test_fees_and_slippage_are_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, rankings, _ = run_crypto_paper_experiments(
                experiment_config=self._experiment_config(fee_bps=20.0, slippage_bps=10.0),
                candles_by_symbol=self._bullish_take_profit_candles(),
                output_dir=Path(tmp),
            )
            result = rankings[0]
            self.assertGreater(result["total_fees"], 0.0)
            self.assertGreater(result["total_slippage"], 0.0)

    def test_metrics_are_calculated_for_each_config_and_ranking_prefers_higher_expectancy(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, rankings, _ = run_crypto_paper_experiments(
                experiment_config=self._experiment_config(
                    grid={
                        "fast_ma_window": [2],
                        "slow_ma_window": [3],
                        "min_abs_signal_strength": [0.0001],
                        "max_volatility_pct": [1.0],
                        "stop_loss_pct": [0.001, 0.02],
                        "take_profit_pct": [0.01],
                    }
                ),
                candles_by_symbol=self._bullish_take_profit_candles(),
                output_dir=Path(tmp),
            )
            self.assertGreaterEqual(len(rankings), 2)
            self.assertGreater((rankings[0]["expectancy"] or 0.0), (rankings[-1]["expectancy"] or float("-inf")))

    def test_low_sample_config_marked_ineligible_and_drawdown_warning_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, rankings, _ = run_crypto_paper_experiments(
                experiment_config=self._experiment_config(ranking={"min_closed_trades": 2}),
                candles_by_symbol=self._bullish_take_profit_candles(),
                output_dir=Path(tmp),
            )
            result = rankings[0]
            self.assertFalse(result["eligible"])
            self.assertIn("closed_trades_below_min", result["disqualification_reasons"])
            self.assertTrue(any("Drawdown calculated" in warning for warning in result["warnings"]))

    def test_artifacts_are_json_serializable_and_markdown_report_is_generated_without_modifying_crypto_config(self):
        crypto_config = REPO_ROOT / "config" / "market_universe" / "crypto.json"
        before = crypto_config.read_text(encoding="utf-8") if crypto_config.exists() else None
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "artifacts"
            summary, rankings, written = run_crypto_paper_experiments(
                experiment_config=self._experiment_config(),
                candles_by_symbol=self._bullish_take_profit_candles(),
                output_dir=output_dir,
            )
            self.assertTrue((output_dir / "crypto_paper_experiment_results.json").exists())
            self.assertTrue((output_dir / "crypto_paper_experiment_report.md").exists())
            json.loads((output_dir / "crypto_paper_experiment_results.json").read_text(encoding="utf-8"))
            json.loads((output_dir / "crypto_paper_experiment_rankings.json").read_text(encoding="utf-8"))
            self.assertTrue(written)
            self.assertTrue(summary["metadata"]["paper_only"])
            self.assertFalse(summary["metadata"]["live_trading"])
            self.assertFalse(rankings[0]["metadata"]["live_trading"])
        after = crypto_config.read_text(encoding="utf-8") if crypto_config.exists() else None
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
