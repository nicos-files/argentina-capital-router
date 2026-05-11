from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.execution.crypto_paper_evaluation import evaluate_crypto_paper_strategy
from src.execution.crypto_paper_forward import (
    _merge_cumulative_records,
    _write_execution_artifacts,
    run_crypto_paper_forward,
)
from src.execution.crypto_paper_models import (
    CryptoPaperExecutionResult,
    CryptoPaperFill,
    CryptoPaperOrder,
    CryptoPaperPortfolioSnapshot,
)


def _candidate_config() -> dict:
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


def _bundle_with_buy_signal() -> dict:
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


def _bundle_no_signal_no_exit(*, price: float) -> dict:
    """Flat-price bundle: no fast/slow crossover, low/high never cross SL/TP."""
    rows = []
    timestamps = [
        "2026-04-26T10:00:00Z",
        "2026-04-26T10:05:00Z",
        "2026-04-26T10:10:00Z",
        "2026-04-26T10:15:00Z",
        "2026-04-26T10:20:00Z",
    ]
    for timestamp in timestamps:
        rows.append(
            {
                "timestamp": timestamp,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 1.0,
            }
        )
    return {"candles": {"BTCUSDT": rows}}


def _write_inputs(root: Path, *, candidate: dict, bundle: dict) -> tuple[Path, Path]:
    candidate_path = root / "candidate.json"
    prices_path = root / "prices.json"
    candidate_path.write_text(json.dumps(candidate, ensure_ascii=False), encoding="utf-8")
    prices_path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    return candidate_path, prices_path


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class CryptoPaperForwardCumulativeArtifactsTests(unittest.TestCase):
    def test_fills_orders_are_cumulative_across_runs_with_no_new_activity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts_dir = root / "artifacts" / "crypto_paper"
            candidate = _candidate_config()

            candidate_path, prices_path = _write_inputs(
                root, candidate=candidate, bundle=_bundle_with_buy_signal()
            )
            run1 = run_crypto_paper_forward(
                candidate_config=candidate_path,
                artifacts_dir=artifacts_dir,
                prices_json=prices_path,
                as_of="2026-04-25T10:20:00+00:00",
            )
            self.assertEqual(run1["status"], "SUCCESS")
            self.assertGreaterEqual(run1["fills_count"], 1)

            fills_path = artifacts_dir / "crypto_paper_fills.json"
            orders_path = artifacts_dir / "crypto_paper_orders.json"
            positions_path = artifacts_dir / "crypto_paper_positions.json"

            fills_after_run1 = _read_json(fills_path)
            orders_after_run1 = _read_json(orders_path)
            positions_after_run1 = _read_json(positions_path)
            self.assertEqual(len(fills_after_run1), 1)
            self.assertGreaterEqual(len(orders_after_run1), 1)
            self.assertEqual(len(positions_after_run1), 1)
            self.assertEqual(positions_after_run1[0]["symbol"], "BTCUSDT")

            entry_price = float(positions_after_run1[0]["avg_entry_price"])

            candidate_path2, prices_path2 = _write_inputs(
                root,
                candidate=candidate,
                bundle=_bundle_no_signal_no_exit(price=entry_price),
            )
            run2 = run_crypto_paper_forward(
                candidate_config=candidate_path2,
                artifacts_dir=artifacts_dir,
                prices_json=prices_path2,
                as_of="2026-04-26T10:20:00+00:00",
            )
            self.assertIn(run2["status"], ("SUCCESS", "PARTIAL"))
            self.assertEqual(run2["fills_count"], 0)
            self.assertEqual(run2["exits_count"], 0)

            fills_after_run2 = _read_json(fills_path)
            orders_after_run2 = _read_json(orders_path)
            positions_after_run2 = _read_json(positions_path)

            self.assertEqual(
                len(fills_after_run2),
                len(fills_after_run1),
                "cumulative fills must not be cleared by a zero-fill run",
            )
            run1_fill_ids = sorted(item.get("fill_id") for item in fills_after_run1)
            run2_fill_ids = sorted(item.get("fill_id") for item in fills_after_run2)
            self.assertEqual(run1_fill_ids, run2_fill_ids)

            run1_order_ids = sorted(item.get("order_id") for item in orders_after_run1)
            run2_order_ids = sorted(item.get("order_id") for item in orders_after_run2)
            self.assertTrue(set(run1_order_ids).issubset(set(run2_order_ids)))

            self.assertEqual(len(positions_after_run2), 1)
            self.assertEqual(positions_after_run2[0]["symbol"], "BTCUSDT")

    def test_exit_events_remain_unchanged_when_no_new_exits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts_dir = root / "artifacts" / "crypto_paper"
            candidate = _candidate_config()
            candidate_path, prices_path = _write_inputs(
                root, candidate=candidate, bundle=_bundle_with_buy_signal()
            )
            run1 = run_crypto_paper_forward(
                candidate_config=candidate_path,
                artifacts_dir=artifacts_dir,
                prices_json=prices_path,
                as_of="2026-04-25T10:20:00+00:00",
            )
            self.assertEqual(run1["status"], "SUCCESS")

            exits_path = artifacts_dir / "crypto_paper_exit_events.json"
            seeded_event = {
                "exit_id": "seeded-exit-0001",
                "symbol": "BTCUSDT",
                "position_quantity_before": 0.1,
                "exit_quantity": 0.1,
                "exit_reason": "SEEDED",
                "trigger_price": 100.0,
                "fill_price": 100.0,
                "gross_notional": 10.0,
                "fee": 0.0,
                "slippage": 0.0,
                "realized_pnl": 0.0,
                "exited_at": "2026-04-24T09:00:00",
                "source": "test_seed",
                "metadata": {},
            }
            exits_path.write_text(
                json.dumps([seeded_event], sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )

            entry_price = float(
                _read_json(artifacts_dir / "crypto_paper_positions.json")[0]["avg_entry_price"]
            )
            candidate_path2, prices_path2 = _write_inputs(
                root,
                candidate=candidate,
                bundle=_bundle_no_signal_no_exit(price=entry_price),
            )
            run2 = run_crypto_paper_forward(
                candidate_config=candidate_path2,
                artifacts_dir=artifacts_dir,
                prices_json=prices_path2,
                as_of="2026-04-26T10:20:00+00:00",
            )
            self.assertEqual(run2["exits_count"], 0)

            exits_after_run2 = _read_json(exits_path)
            exit_ids = [item.get("exit_id") for item in exits_after_run2]
            self.assertIn("seeded-exit-0001", exit_ids)

    def test_evaluation_reconstructs_one_open_trade_from_cumulative_fills(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts_dir = root / "artifacts" / "crypto_paper"
            candidate = _candidate_config()
            candidate_path, prices_path = _write_inputs(
                root, candidate=candidate, bundle=_bundle_with_buy_signal()
            )
            run_crypto_paper_forward(
                candidate_config=candidate_path,
                artifacts_dir=artifacts_dir,
                prices_json=prices_path,
                as_of="2026-04-25T10:20:00+00:00",
            )

            entry_price = float(
                _read_json(artifacts_dir / "crypto_paper_positions.json")[0]["avg_entry_price"]
            )
            candidate_path2, prices_path2 = _write_inputs(
                root,
                candidate=candidate,
                bundle=_bundle_no_signal_no_exit(price=entry_price),
            )
            run2 = run_crypto_paper_forward(
                candidate_config=candidate_path2,
                artifacts_dir=artifacts_dir,
                prices_json=prices_path2,
                as_of="2026-04-26T10:20:00+00:00",
            )

            evaluation = run2.get("evaluation") or {}
            self.assertEqual(
                evaluation.get("open_trades_count"), 1,
                "cumulative fills should let evaluation reconstruct the open trade",
            )

    def test_inconsistent_state_emits_ledger_history_warning_without_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts_dir = root / "artifacts" / "crypto_paper"
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            (artifacts_dir / "crypto_paper_fills.json").write_text(
                json.dumps([], sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            (artifacts_dir / "crypto_paper_orders.json").write_text(
                json.dumps([], sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            (artifacts_dir / "crypto_paper_exit_events.json").write_text(
                json.dumps([], sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            (artifacts_dir / "crypto_paper_positions.json").write_text(
                json.dumps(
                    [
                        {
                            "symbol": "BTCUSDT",
                            "quantity": 0.001,
                            "avg_entry_price": 76000.0,
                            "realized_pnl": 0.0,
                            "unrealized_pnl": 0.0,
                            "last_price": 76000.0,
                            "updated_at": "2026-04-25T10:20:00",
                            "metadata": {},
                        }
                    ],
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            (artifacts_dir / "crypto_paper_snapshot.json").write_text(
                json.dumps(
                    {
                        "as_of": "2026-04-25T10:20:00",
                        "cash": 75.0,
                        "equity": 100.0,
                        "positions_value": 25.0,
                        "realized_pnl": 0.0,
                        "unrealized_pnl": 0.0,
                        "fees_paid": 0.0,
                        "positions": [
                            {
                                "symbol": "BTCUSDT",
                                "quantity": 0.001,
                                "avg_entry_price": 76000.0,
                                "realized_pnl": 0.0,
                                "unrealized_pnl": 0.0,
                                "last_price": 76000.0,
                                "updated_at": "2026-04-25T10:20:00",
                                "metadata": {},
                            }
                        ],
                        "metadata": {},
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )

            closed_trades, open_trades, metrics, _, _, _, all_warnings = evaluate_crypto_paper_strategy(
                artifacts_dir=artifacts_dir,
                output_dir=artifacts_dir / "evaluation",
            )
            self.assertEqual(closed_trades, [])
            self.assertEqual(open_trades, [])
            self.assertTrue(
                any("ledger_history_inconsistency" in str(item) for item in all_warnings),
                f"expected ledger_history_inconsistency warning, got: {all_warnings}",
            )
            self.assertTrue(
                any("ledger_history_inconsistency" in str(item) for item in metrics.warnings),
                f"expected ledger_history_inconsistency warning in metrics, got: {metrics.warnings}",
            )


class CryptoPaperCumulativeIdCollisionTests(unittest.TestCase):
    def test_two_fills_with_same_fill_id_but_different_content_are_both_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "crypto_paper_fills.json"
            existing = [
                {
                    "fill_id": "crypto-paper-fill-0001",
                    "order_id": "crypto-paper-order-0001",
                    "symbol": "BTCUSDT",
                    "side": "BUY",
                    "quantity": 0.001,
                    "fill_price": 76000.0,
                    "gross_notional": 76.0,
                    "fee": 0.025,
                    "slippage": 0.0,
                    "net_notional": 76.025,
                    "filled_at": "2026-04-29T12:00:00",
                    "metadata": {"day": "first"},
                }
            ]
            path.write_text(json.dumps(existing, sort_keys=True, separators=(",", ":")), encoding="utf-8")

            current = [
                {
                    "fill_id": "crypto-paper-fill-0001",
                    "order_id": "crypto-paper-order-0001",
                    "symbol": "BTCUSDT",
                    "side": "BUY",
                    "quantity": 0.001,
                    "fill_price": 77000.0,
                    "gross_notional": 77.0,
                    "fee": 0.025,
                    "slippage": 0.0,
                    "net_notional": 77.025,
                    "filled_at": "2026-04-30T12:00:00",
                    "metadata": {"day": "second"},
                }
            ]

            merged, warnings = _merge_cumulative_records(
                path=path,
                current=current,
                id_key="fill_id",
                sort_keys=("filled_at", "fill_id"),
            )
            self.assertEqual(len(merged), 2, f"expected both fills preserved, got {merged}")
            filled_ats = sorted(item["filled_at"] for item in merged)
            self.assertEqual(filled_ats, ["2026-04-29T12:00:00", "2026-04-30T12:00:00"])
            self.assertTrue(
                any("id_collision_with_diff_content:fill_id=crypto-paper-fill-0001" in w for w in warnings),
                f"expected id-collision warning, got: {warnings}",
            )

    def test_identical_fill_with_same_id_is_deduplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "crypto_paper_fills.json"
            record = {
                "fill_id": "crypto-paper-fill-0001",
                "order_id": "crypto-paper-order-0001",
                "symbol": "BTCUSDT",
                "side": "BUY",
                "quantity": 0.001,
                "fill_price": 76000.0,
                "gross_notional": 76.0,
                "fee": 0.025,
                "slippage": 0.0,
                "net_notional": 76.025,
                "filled_at": "2026-04-29T12:00:00",
                "metadata": {"day": "first"},
            }
            path.write_text(
                json.dumps([record], sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            merged, warnings = _merge_cumulative_records(
                path=path,
                current=[dict(record)],
                id_key="fill_id",
                sort_keys=("filled_at", "fill_id"),
            )
            self.assertEqual(len(merged), 1)
            self.assertEqual(warnings, [])

    def test_rejected_order_does_not_overwrite_prior_accepted_order_with_same_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "crypto_paper_orders.json"
            accepted = {
                "order_id": "crypto-paper-order-0001",
                "symbol": "BTCUSDT",
                "side": "BUY",
                "requested_notional": 25.0,
                "requested_quantity": None,
                "reference_price": 76000.0,
                "status": "PENDING",
                "reason": None,
                "created_at": "2026-04-29T12:00:00",
                "metadata": {},
            }
            path.write_text(
                json.dumps([accepted], sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            rejected = dict(accepted)
            rejected["status"] = "REJECTED"
            rejected["reason"] = "insufficient_cash"
            rejected["created_at"] = "2026-04-30T12:00:00"

            merged, warnings = _merge_cumulative_records(
                path=path,
                current=[rejected],
                id_key="order_id",
                sort_keys=("created_at", "order_id"),
            )
            statuses = sorted(item["status"] for item in merged)
            self.assertEqual(statuses, ["PENDING", "REJECTED"])
            self.assertTrue(
                any("id_collision_with_diff_content:order_id=crypto-paper-order-0001" in w for w in warnings),
                f"expected id-collision warning, got: {warnings}",
            )

    def test_executor_generated_ids_are_globally_unique_across_two_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifacts_dir = root / "artifacts" / "crypto_paper"
            candidate = _candidate_config()
            candidate_path, prices_path = _write_inputs(
                root, candidate=candidate, bundle=_bundle_with_buy_signal()
            )
            run1 = run_crypto_paper_forward(
                candidate_config=candidate_path,
                artifacts_dir=artifacts_dir,
                prices_json=prices_path,
                as_of="2026-04-29T10:20:00+00:00",
            )
            self.assertEqual(run1["status"], "SUCCESS")
            self.assertGreaterEqual(run1["fills_count"], 1)
            fills_after_run1 = _read_json(artifacts_dir / "crypto_paper_fills.json")
            run1_fill_ids = sorted(item["fill_id"] for item in fills_after_run1)

            candidate2 = dict(candidate)
            candidate2["strategy"] = dict(candidate["strategy"])
            candidate2["strategy"]["max_paper_notional"] = 20.0
            bundle2 = _bundle_with_buy_signal_offset(start="2026-04-30T10:00:00Z")
            candidate_path2, prices_path2 = _write_inputs(
                root, candidate=candidate2, bundle=bundle2
            )
            run2 = run_crypto_paper_forward(
                candidate_config=candidate_path2,
                artifacts_dir=artifacts_dir,
                prices_json=prices_path2,
                as_of="2026-04-30T10:20:00+00:00",
            )
            self.assertIn(run2["status"], ("SUCCESS", "PARTIAL"))
            self.assertGreaterEqual(run2["fills_count"], 1)

            fills_after_run2 = _read_json(artifacts_dir / "crypto_paper_fills.json")
            run2_fill_ids = sorted(item["fill_id"] for item in fills_after_run2)

            self.assertGreater(
                len(run2_fill_ids),
                len(run1_fill_ids),
                "cumulative fills must grow when a second run produces new fills",
            )
            for fill_id in run1_fill_ids:
                self.assertIn(fill_id, run2_fill_ids)

            for fill in fills_after_run2:
                self.assertRegex(
                    fill["fill_id"],
                    r"crypto-paper-(?:exit-)?fill-\d{8}T\d{6}-\d{4}",
                    f"expected timestamped fill_id, got: {fill['fill_id']}",
                )

            orders_after_run2 = _read_json(artifacts_dir / "crypto_paper_orders.json")
            for order in orders_after_run2:
                self.assertRegex(
                    order["order_id"],
                    r"crypto-paper(?:-exit)?-order-\d{8}T\d{6}-\d{4}",
                    f"expected timestamped order_id, got: {order['order_id']}",
                )

    def test_evaluation_reconstructs_multiple_open_lots_from_multiple_cumulative_fills(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifacts_dir = Path(tmp) / "artifacts" / "crypto_paper"
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            fills = [
                {
                    "fill_id": "crypto-paper-fill-20260429T120000-0001",
                    "order_id": "crypto-paper-order-20260429T120000-0001",
                    "symbol": "BTCUSDT",
                    "side": "BUY",
                    "quantity": 0.001,
                    "fill_price": 76000.0,
                    "gross_notional": 76.0,
                    "fee": 0.025,
                    "slippage": 0.0,
                    "net_notional": 76.025,
                    "filled_at": "2026-04-29T12:00:00",
                    "metadata": {},
                },
                {
                    "fill_id": "crypto-paper-fill-20260430T120000-0001",
                    "order_id": "crypto-paper-order-20260430T120000-0001",
                    "symbol": "BTCUSDT",
                    "side": "BUY",
                    "quantity": 0.001,
                    "fill_price": 77000.0,
                    "gross_notional": 77.0,
                    "fee": 0.025,
                    "slippage": 0.0,
                    "net_notional": 77.025,
                    "filled_at": "2026-04-30T12:00:00",
                    "metadata": {},
                },
            ]
            (artifacts_dir / "crypto_paper_fills.json").write_text(
                json.dumps(fills, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            (artifacts_dir / "crypto_paper_orders.json").write_text(
                json.dumps([], sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            (artifacts_dir / "crypto_paper_exit_events.json").write_text(
                json.dumps([], sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            (artifacts_dir / "crypto_paper_snapshot.json").write_text(
                json.dumps(
                    {
                        "as_of": "2026-04-30T12:00:00",
                        "cash": 47.95,
                        "equity": 200.0,
                        "positions_value": 152.05,
                        "realized_pnl": 0.0,
                        "unrealized_pnl": 0.0,
                        "fees_paid": 0.05,
                        "positions": [
                            {
                                "symbol": "BTCUSDT",
                                "quantity": 0.002,
                                "avg_entry_price": 76500.0,
                                "realized_pnl": 0.0,
                                "unrealized_pnl": 0.0,
                                "last_price": 77000.0,
                                "updated_at": "2026-04-30T12:00:00",
                                "metadata": {},
                            }
                        ],
                        "metadata": {},
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
            (artifacts_dir / "crypto_paper_positions.json").write_text(
                json.dumps(
                    [
                        {
                            "symbol": "BTCUSDT",
                            "quantity": 0.002,
                            "avg_entry_price": 76500.0,
                            "realized_pnl": 0.0,
                            "unrealized_pnl": 0.0,
                            "last_price": 77000.0,
                            "updated_at": "2026-04-30T12:00:00",
                            "metadata": {},
                        }
                    ],
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )

            closed_trades, open_trades, _, _, _, _, _ = evaluate_crypto_paper_strategy(
                artifacts_dir=artifacts_dir,
                output_dir=artifacts_dir / "evaluation",
            )
            self.assertEqual(closed_trades, [])
            self.assertEqual(
                len(open_trades), 2,
                f"expected two open lots reconstructed from cumulative fills, got: {open_trades}",
            )

    def test_writer_returns_id_collision_warning_when_existing_record_collides(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_root = Path(tmp)
            artifact_root.mkdir(parents=True, exist_ok=True)
            existing_fill = {
                "fill_id": "crypto-paper-fill-0001",
                "order_id": "crypto-paper-order-0001",
                "symbol": "BTCUSDT",
                "side": "BUY",
                "quantity": 0.001,
                "fill_price": 76000.0,
                "gross_notional": 76.0,
                "fee": 0.025,
                "slippage": 0.0,
                "net_notional": 76.025,
                "filled_at": "2026-04-29T12:00:00",
                "metadata": {"day": "first"},
            }
            (artifact_root / "crypto_paper_fills.json").write_text(
                json.dumps([existing_fill], sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            (artifact_root / "crypto_paper_orders.json").write_text(
                json.dumps([], sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )

            colliding_fill = CryptoPaperFill(
                fill_id="crypto-paper-fill-0001",
                order_id="crypto-paper-order-0001",
                symbol="BTCUSDT",
                side="BUY",
                quantity=0.001,
                fill_price=77000.0,
                gross_notional=77.0,
                fee=0.025,
                slippage=0.0,
                net_notional=77.025,
                filled_at=__import__("datetime").datetime.fromisoformat("2026-04-30T12:00:00"),
                metadata={"day": "second"},
            )
            colliding_order = CryptoPaperOrder(
                order_id="crypto-paper-order-0001",
                symbol="BTCUSDT",
                side="BUY",
                requested_notional=25.0,
                requested_quantity=None,
                reference_price=77000.0,
                status="PENDING",
                reason=None,
                created_at=__import__("datetime").datetime.fromisoformat("2026-04-30T12:00:00"),
                metadata={},
            )
            snapshot = CryptoPaperPortfolioSnapshot(
                as_of=__import__("datetime").datetime.fromisoformat("2026-04-30T12:00:00"),
                cash=23.0,
                equity=100.0,
                positions_value=77.0,
                realized_pnl=0.0,
                unrealized_pnl=0.0,
                fees_paid=0.05,
                positions=[],
                metadata={},
            )
            result = CryptoPaperExecutionResult(
                accepted_orders=[colliding_order],
                rejected_orders=[],
                fills=[colliding_fill],
                portfolio_snapshot=snapshot,
                warnings=[],
                exit_events=[],
                metadata={},
            )

            writer_warnings = _write_execution_artifacts(artifact_root=artifact_root, result=result)
            self.assertTrue(
                any("id_collision_with_diff_content:fill_id=crypto-paper-fill-0001" in w for w in writer_warnings),
                f"expected fill collision warning, got: {writer_warnings}",
            )

            persisted_fills = _read_json(artifact_root / "crypto_paper_fills.json")
            self.assertEqual(len(persisted_fills), 2)


def _bundle_with_buy_signal_offset(*, start: str) -> dict:
    """Variant of _bundle_with_buy_signal with a different starting timestamp."""

    base = pd_like_offsets(start)
    return {
        "candles": {
            "BTCUSDT": [
                {"timestamp": base[0], "open": 200.0, "high": 200.5, "low": 199.5, "close": 200.0, "volume": 10.0},
                {"timestamp": base[1], "open": 200.0, "high": 201.5, "low": 199.9, "close": 201.0, "volume": 10.0},
                {"timestamp": base[2], "open": 201.0, "high": 202.5, "low": 200.9, "close": 202.0, "volume": 11.0},
                {"timestamp": base[3], "open": 202.0, "high": 203.5, "low": 201.8, "close": 203.0, "volume": 12.0},
                {"timestamp": base[4], "open": 203.0, "high": 204.0, "low": 202.8, "close": 203.5, "volume": 12.0},
            ]
        }
    }


def pd_like_offsets(start_iso: str) -> list[str]:
    import pandas as pd

    base_ts = pd.Timestamp(start_iso)
    return [(base_ts + pd.Timedelta(minutes=5 * idx)).strftime("%Y-%m-%dT%H:%M:%SZ") for idx in range(5)]


if __name__ == "__main__":
    unittest.main()
