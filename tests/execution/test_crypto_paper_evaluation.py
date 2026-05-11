import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.execution.crypto_paper_evaluation import evaluate_crypto_paper_strategy
from src.execution.crypto_paper_models import CryptoPaperExitEvent, CryptoPaperFill, CryptoPaperPortfolioSnapshot, CryptoPaperPosition


class CryptoPaperEvaluationTests(unittest.TestCase):
    def _fill(
        self,
        fill_id: str,
        side: str,
        symbol: str = "BTCUSDT",
        qty: float = 0.1,
        price: float = 100.0,
        gross: float | None = None,
        fee: float = 0.1,
        slippage: float = 0.05,
        filled_at: datetime | None = None,
        metadata: dict | None = None,
    ) -> CryptoPaperFill:
        when = filled_at or datetime(2026, 4, 25, 10, 0, 0)
        gross_notional = gross if gross is not None else qty * price
        return CryptoPaperFill(
            fill_id=fill_id,
            order_id=f"order-{fill_id}",
            symbol=symbol,
            side=side,
            quantity=qty,
            fill_price=price,
            gross_notional=gross_notional,
            fee=fee,
            slippage=slippage,
            net_notional=(gross_notional + fee) if side == "BUY" else (gross_notional - fee),
            filled_at=when,
            metadata=metadata or {},
        )

    def _exit_event(
        self,
        exit_id: str,
        symbol: str = "BTCUSDT",
        qty: float = 0.1,
        reason: str = "TAKE_PROFIT",
        trigger: float = 110.0,
        exited_at: datetime | None = None,
    ) -> CryptoPaperExitEvent:
        when = exited_at or datetime(2026, 4, 25, 11, 0, 0)
        return CryptoPaperExitEvent(
            exit_id=exit_id,
            symbol=symbol,
            position_quantity_before=qty,
            exit_quantity=qty,
            exit_reason=reason,
            trigger_price=trigger,
            fill_price=trigger,
            gross_notional=qty * trigger,
            fee=0.01,
            slippage=0.05,
            realized_pnl=0.0,
            exited_at=when,
            source="unit",
        )

    def _write_artifacts(
        self,
        root: Path,
        *,
        fills: list[CryptoPaperFill],
        exit_events: list[CryptoPaperExitEvent] | None = None,
        positions: list[CryptoPaperPosition] | None = None,
    ) -> None:
        root.mkdir(parents=True, exist_ok=True)
        (root / "crypto_paper_fills.json").write_text(json.dumps([fill.to_dict() for fill in fills], ensure_ascii=False), encoding="utf-8")
        (root / "crypto_paper_exit_events.json").write_text(json.dumps([event.to_dict() for event in (exit_events or [])], ensure_ascii=False), encoding="utf-8")
        (root / "crypto_paper_orders.json").write_text(json.dumps([], ensure_ascii=False), encoding="utf-8")
        snapshot = CryptoPaperPortfolioSnapshot(
            as_of=datetime(2026, 4, 25, 12, 0, 0),
            cash=100.0,
            equity=100.0,
            positions_value=sum((position.last_price or position.avg_entry_price) * position.quantity for position in (positions or [])),
            realized_pnl=0.0,
            unrealized_pnl=sum(position.unrealized_pnl for position in (positions or [])),
            fees_paid=sum(fill.fee for fill in fills),
            positions=positions or [],
        )
        (root / "crypto_paper_snapshot.json").write_text(json.dumps(snapshot.to_dict(), ensure_ascii=False), encoding="utf-8")

    def test_no_fills_produces_no_closed_trades_and_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_artifacts(root, fills=[])
            closed, open_trades, metrics, _, _, _, warnings = evaluate_crypto_paper_strategy(root)
            self.assertEqual(closed, [])
            self.assertEqual(metrics.closed_trades_count, 0)
            self.assertTrue(warnings)

    def test_buy_without_exit_produces_open_trade(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            buy = self._fill("b1", "BUY")
            position = CryptoPaperPosition("BTCUSDT", 0.1, 100.0, 0.0, 0.4, 104.0, datetime(2026, 4, 25, 10, 0, 0))
            self._write_artifacts(root, fills=[buy], positions=[position])
            closed, open_trades, metrics, _, _, _, _ = evaluate_crypto_paper_strategy(root)
            self.assertEqual(len(closed), 0)
            self.assertEqual(len(open_trades), 1)
            self.assertEqual(metrics.open_trades_count, 1)

    def test_buy_plus_stop_loss_exit_is_closed_loss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            buy = self._fill("b1", "BUY", price=100.0, fee=0.1)
            sell = self._fill("s1", "SELL", price=95.0, fee=0.1, filled_at=datetime(2026, 4, 25, 11, 0, 0), metadata={"exit_reason": "STOP_LOSS"})
            self._write_artifacts(root, fills=[buy, sell], exit_events=[self._exit_event("e1", reason="STOP_LOSS", trigger=95.0)])
            closed, _, metrics, breakdown, _, _, _ = evaluate_crypto_paper_strategy(root)
            self.assertEqual(len(closed), 1)
            self.assertEqual(closed[0].result, "LOSS")
            self.assertEqual(metrics.losing_trades_count, 1)
            self.assertEqual(breakdown["STOP_LOSS"]["count"], 1)

    def test_buy_plus_take_profit_exit_is_closed_win(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            buy = self._fill("b1", "BUY", price=100.0, fee=0.1)
            sell = self._fill("s1", "SELL", price=110.0, fee=0.1, filled_at=datetime(2026, 4, 25, 11, 0, 0), metadata={"exit_reason": "TAKE_PROFIT"})
            self._write_artifacts(root, fills=[buy, sell], exit_events=[self._exit_event("e1", reason="TAKE_PROFIT", trigger=110.0)])
            closed, _, metrics, breakdown, _, _, _ = evaluate_crypto_paper_strategy(root)
            self.assertEqual(closed[0].result, "WIN")
            self.assertEqual(metrics.winning_trades_count, 1)
            self.assertEqual(breakdown["TAKE_PROFIT"]["count"], 1)

    def test_fees_reduce_net_pnl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            buy = self._fill("b1", "BUY", price=100.0, fee=0.5)
            sell = self._fill("s1", "SELL", price=110.0, fee=0.5, filled_at=datetime(2026, 4, 25, 11, 0, 0), metadata={"exit_reason": "TAKE_PROFIT"})
            self._write_artifacts(root, fills=[buy, sell])
            closed, _, _, _, _, _, _ = evaluate_crypto_paper_strategy(root)
            self.assertLess(closed[0].net_pnl, closed[0].gross_pnl)

    def test_slippage_is_included(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            buy = self._fill("b1", "BUY", slippage=0.1)
            sell = self._fill("s1", "SELL", price=110.0, slippage=0.2, filled_at=datetime(2026, 4, 25, 11, 0, 0), metadata={"exit_reason": "TAKE_PROFIT"})
            self._write_artifacts(root, fills=[buy, sell])
            closed, _, _, _, fee_report, _, _ = evaluate_crypto_paper_strategy(root)
            self.assertGreater(closed[0].total_slippage, 0.0)
            self.assertGreater(fee_report["total_slippage"], 0.0)

    def test_metrics_and_expectancy_are_calculated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fills = [
                self._fill("b1", "BUY", price=100.0, fee=0.1, filled_at=datetime(2026, 4, 25, 10, 0, 0)),
                self._fill("s1", "SELL", price=110.0, fee=0.1, filled_at=datetime(2026, 4, 25, 11, 0, 0), metadata={"exit_reason": "TAKE_PROFIT"}),
                self._fill("b2", "BUY", price=100.0, fee=0.1, filled_at=datetime(2026, 4, 25, 12, 0, 0)),
                self._fill("s2", "SELL", price=95.0, fee=0.1, filled_at=datetime(2026, 4, 25, 13, 0, 0), metadata={"exit_reason": "STOP_LOSS"}),
            ]
            self._write_artifacts(root, fills=fills)
            _, _, metrics, _, fee_report, _, _ = evaluate_crypto_paper_strategy(root)
            self.assertAlmostEqual(metrics.win_rate, 0.5, places=6)
            self.assertIsNotNone(metrics.average_win)
            self.assertIsNotNone(metrics.average_loss)
            self.assertIsNotNone(metrics.expectancy)
            self.assertIsNotNone(metrics.profit_factor)
            self.assertIsNotNone(fee_report["fee_drag_pct_of_gross_pnl"])

    def test_consecutive_streaks_and_per_symbol_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fills = [
                self._fill("b1", "BUY", symbol="BTCUSDT", filled_at=datetime(2026, 4, 25, 10, 0, 0)),
                self._fill("s1", "SELL", symbol="BTCUSDT", price=110.0, filled_at=datetime(2026, 4, 25, 11, 0, 0), metadata={"exit_reason": "TAKE_PROFIT"}),
                self._fill("b2", "BUY", symbol="ETHUSDT", filled_at=datetime(2026, 4, 25, 12, 0, 0)),
                self._fill("s2", "SELL", symbol="ETHUSDT", price=111.0, filled_at=datetime(2026, 4, 25, 13, 0, 0), metadata={"exit_reason": "TAKE_PROFIT"}),
            ]
            self._write_artifacts(root, fills=fills)
            _, _, metrics, breakdown, _, _, _ = evaluate_crypto_paper_strategy(root)
            self.assertEqual(metrics.consecutive_wins_max, 2)
            self.assertIn("BTCUSDT", metrics.per_symbol_metrics)
            self.assertEqual(breakdown["TAKE_PROFIT"]["count"], 2)

    def test_same_symbol_multiple_trades_are_paired_fifo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fills = [
                self._fill("b1", "BUY", qty=0.1, price=100.0, filled_at=datetime(2026, 4, 25, 10, 0, 0)),
                self._fill("b2", "BUY", qty=0.2, price=120.0, gross=24.0, filled_at=datetime(2026, 4, 25, 10, 5, 0)),
                self._fill("s1", "SELL", qty=0.1, price=130.0, gross=13.0, filled_at=datetime(2026, 4, 25, 11, 0, 0), metadata={"exit_reason": "TAKE_PROFIT"}),
            ]
            self._write_artifacts(root, fills=fills, positions=[CryptoPaperPosition("BTCUSDT", 0.2, 120.0, 0.0, 0.0, 121.0, datetime(2026, 4, 25, 10, 5, 0))])
            closed, open_trades, _, _, _, _, _ = evaluate_crypto_paper_strategy(root)
            self.assertEqual(len(closed), 1)
            self.assertEqual(closed[0].entry_fill_id, "b1")
            self.assertEqual(len(open_trades), 1)
            self.assertEqual(open_trades[0].entry_fill_id, "b2")

    def test_markdown_and_json_outputs_are_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            buy = self._fill("b1", "BUY")
            sell = self._fill("s1", "SELL", price=110.0, filled_at=datetime(2026, 4, 25, 11, 0, 0), metadata={"exit_reason": "TAKE_PROFIT"})
            self._write_artifacts(root, fills=[buy, sell])
            _, _, metrics, _, _, written, _ = evaluate_crypto_paper_strategy(root)
            self.assertTrue((root / "evaluation" / "crypto_paper_trade_log.json").exists())
            self.assertTrue((root / "evaluation" / "crypto_paper_strategy_evaluation_report.md").exists())
            json.loads((root / "evaluation" / "crypto_paper_trade_log.json").read_text(encoding="utf-8"))
            self.assertTrue(metrics.warnings)
            self.assertFalse(metrics.live_trading)


if __name__ == "__main__":
    unittest.main()
