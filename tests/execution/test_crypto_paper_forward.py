import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.execution.crypto_paper_forward import run_crypto_paper_forward


class CryptoPaperForwardTests(unittest.TestCase):
    def _candidate_config(self, **overrides) -> dict:
        base = {
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
                    "base": "BTC",
                    "quote": "USDT",
                    "exchange": "binance_spot",
                    "asset_class": "crypto",
                    "enabled": True,
                    "min_timeframe": "1m",
                    "strategy_enabled": True,
                    "paper_enabled": True,
                    "live_enabled": False,
                }
            ],
        }
        for key, value in overrides.items():
            if key == "strategy":
                merged = dict(base["strategy"])
                merged.update(value)
                base["strategy"] = merged
            else:
                base[key] = value
        return base

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

    def _write_candidate_and_prices(self, root: Path, *, candidate: dict | None = None, bundle: dict | None = None) -> tuple[Path, Path]:
        candidate_path = root / "candidate.json"
        prices_path = root / "prices.json"
        candidate_path.write_text(json.dumps(candidate or self._candidate_config(), ensure_ascii=False), encoding="utf-8")
        prices_path.write_text(json.dumps(bundle or self._prices_bundle(), ensure_ascii=False), encoding="utf-8")
        return candidate_path, prices_path

    def test_candidate_with_live_enabled_true_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = self._candidate_config()
            candidate["symbols"][0]["live_enabled"] = True
            candidate_path, prices_path = self._write_candidate_and_prices(root, candidate=candidate)
            result = run_crypto_paper_forward(
                candidate_config=candidate_path,
                artifacts_dir=root / "artifacts" / "crypto_paper",
                prices_json=prices_path,
            )
            self.assertEqual(result["status"], "FAILED")
            self.assertIn("live_enabled_true:BTCUSDT", result["validation_errors"])

    def test_candidate_with_api_keys_or_broker_settings_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = self._candidate_config()
            candidate["api_key"] = "secret"
            candidate["broker_settings"] = {"name": "bad"}
            candidate_path, prices_path = self._write_candidate_and_prices(root, candidate=candidate)
            result = run_crypto_paper_forward(
                candidate_config=candidate_path,
                artifacts_dir=root / "artifacts" / "crypto_paper",
                prices_json=prices_path,
            )
            self.assertEqual(result["status"], "FAILED")
            self.assertIn("candidate_contains_api_keys", result["validation_errors"])
            self.assertIn("candidate_contains_broker_settings", result["validation_errors"])

    def test_valid_candidate_runs_with_static_data_and_writes_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate_path, prices_path = self._write_candidate_and_prices(root)
            artifacts_dir = root / "artifacts" / "crypto_paper"
            result = run_crypto_paper_forward(
                candidate_config=candidate_path,
                artifacts_dir=artifacts_dir,
                prices_json=prices_path,
                as_of="2026-04-25T10:20:00+00:00",
            )
            self.assertEqual(result["status"], "SUCCESS")
            self.assertTrue((artifacts_dir / "paper_forward" / "crypto_paper_forward_result.json").exists())
            self.assertTrue((artifacts_dir / "paper_forward" / "crypto_paper_forward_report.md").exists())
            self.assertTrue((artifacts_dir / "paper_forward" / "crypto_manual_trade_tickets.json").exists())
            self.assertGreaterEqual(result["manual_trade_ticket_count"], 1)

    def test_no_execution_plan_or_equity_artifacts_are_touched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate_path, prices_path = self._write_candidate_and_prices(root)
            artifacts_dir = root / "artifacts" / "crypto_paper"
            equity_artifact = root / "artifacts" / "paper.day_close.v1.0.0.json"
            execution_plan = root / "artifacts" / "execution.plan.v1.0.0.json"
            equity_artifact.parent.mkdir(parents=True, exist_ok=True)
            equity_artifact.write_text("{}", encoding="utf-8")
            execution_plan.write_text("{}", encoding="utf-8")
            result = run_crypto_paper_forward(
                candidate_config=candidate_path,
                artifacts_dir=artifacts_dir,
                prices_json=prices_path,
                as_of="2026-04-25T10:20:00+00:00",
            )
            self.assertEqual(result["status"], "SUCCESS")
            self.assertEqual(equity_artifact.read_text(encoding="utf-8"), "{}")
            self.assertEqual(execution_plan.read_text(encoding="utf-8"), "{}")

    def _seed_open_position(self, artifacts_dir: Path) -> None:
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        position = {
            "symbol": "BTCUSDT",
            "quantity": 0.0009831395632918993,
            "avg_entry_price": 76286.21896658644,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "last_price": 76500.0,
            "updated_at": "2026-04-25T10:00:00",
            "metadata": {
                "provider": "binance_spot",
                "stop_loss": 74840.444,
                "take_profit": 77131.478,
            },
        }
        snapshot = {
            "as_of": "2026-04-25T10:00:00",
            "cash": 24.925,
            "equity": 100.0,
            "positions_value": 75.075,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "fees_paid": 0.075,
            "positions": [position],
            "metadata": {"quote_currency": "USDT"},
        }
        (artifacts_dir / "crypto_paper_positions.json").write_text(
            json.dumps([position], sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        (artifacts_dir / "crypto_paper_snapshot.json").write_text(
            json.dumps(snapshot, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )

    def test_open_long_above_take_profit_closes_via_quote_fallback_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts_dir = root / "artifacts" / "crypto_paper"
            self._seed_open_position(artifacts_dir)

            # Bundle: no candle bar crosses TP (high stays at 76600), but the
            # latest quote's last_price is well above TP. Candle path will not
            # fire; quote fallback must close the position.
            bundle = {
                "candles": {
                    "BTCUSDT": [
                        {"timestamp": "2026-05-03T17:20:00Z", "open": 76500, "high": 76600, "low": 76400, "close": 76550, "volume": 1.0},
                        {"timestamp": "2026-05-03T17:25:00Z", "open": 76550, "high": 76600, "low": 76450, "close": 76580, "volume": 1.0},
                    ]
                },
                "quotes": {
                    "BTCUSDT": {"last_price": 78734.06, "bid": 78700.0, "ask": 78750.0}
                },
            }
            candidate_path, prices_path = self._write_candidate_and_prices(root, bundle=bundle)
            result = run_crypto_paper_forward(
                candidate_config=candidate_path,
                artifacts_dir=artifacts_dir,
                prices_json=prices_path,
                as_of="2026-05-03T17:30:00+00:00",
            )

            self.assertEqual(result["status"], "SUCCESS", msg=result.get("warnings"))
            self.assertEqual(result["exits_count"], 1, msg=result)
            self.assertGreater(result["realized_pnl"], 0.0)

            exit_events = json.loads(
                (artifacts_dir / "crypto_paper_exit_events.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(exit_events), 1)
            self.assertEqual(exit_events[0]["exit_reason"], "TAKE_PROFIT")
            self.assertEqual(exit_events[0]["source"], "stop_take_quote_fallback")

            positions = json.loads(
                (artifacts_dir / "crypto_paper_positions.json").read_text(encoding="utf-8")
            )
            self.assertEqual(positions, [], msg="expected position fully closed after TP exit")

    def test_open_long_below_stop_loss_closes_via_quote_fallback_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts_dir = root / "artifacts" / "crypto_paper"
            self._seed_open_position(artifacts_dir)

            bundle = {
                "candles": {
                    "BTCUSDT": [
                        {"timestamp": "2026-05-03T17:20:00Z", "open": 76200, "high": 76300, "low": 76100, "close": 76250, "volume": 1.0},
                        {"timestamp": "2026-05-03T17:25:00Z", "open": 76250, "high": 76300, "low": 76150, "close": 76280, "volume": 1.0},
                    ]
                },
                "quotes": {
                    "BTCUSDT": {"last_price": 70000.0, "bid": 69990.0, "ask": 70010.0}
                },
            }
            candidate_path, prices_path = self._write_candidate_and_prices(root, bundle=bundle)
            result = run_crypto_paper_forward(
                candidate_config=candidate_path,
                artifacts_dir=artifacts_dir,
                prices_json=prices_path,
                as_of="2026-05-03T17:30:00+00:00",
            )

            self.assertEqual(result["status"], "SUCCESS", msg=result.get("warnings"))
            self.assertEqual(result["exits_count"], 1, msg=result)

            exit_events = json.loads(
                (artifacts_dir / "crypto_paper_exit_events.json").read_text(encoding="utf-8")
            )
            self.assertEqual(exit_events[0]["exit_reason"], "STOP_LOSS")
            self.assertEqual(exit_events[0]["source"], "stop_take_quote_fallback")

    def test_partial_failure_produces_warnings_not_silent_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate_path, prices_path = self._write_candidate_and_prices(root)
            artifacts_dir = root / "artifacts" / "crypto_paper"
            with patch("src.execution.crypto_paper_forward.evaluate_crypto_paper_strategy", side_effect=RuntimeError("boom")):
                result = run_crypto_paper_forward(
                    candidate_config=candidate_path,
                    artifacts_dir=artifacts_dir,
                    prices_json=prices_path,
                    as_of="2026-04-25T10:20:00+00:00",
                )
            self.assertEqual(result["status"], "PARTIAL")
            self.assertTrue(any("evaluation_failed:boom" in warning for warning in result["warnings"]))


if __name__ == "__main__":
    unittest.main()
