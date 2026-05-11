import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.execution.crypto_paper_daily_close import close_crypto_paper_day
from src.execution.crypto_paper_models import (
    CryptoPaperExecutionResult,
    CryptoPaperExitEvent,
    CryptoPaperFill,
    CryptoPaperOrder,
    CryptoPaperPortfolioSnapshot,
    CryptoPaperPosition,
)


class CryptoPaperDailyCloseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.as_of = datetime(2026, 4, 24, 19, 0, 0)

    def _write_artifacts(self, root: Path, last_price: float = 102.0, realized_pnl: float = 0.0, with_exit: bool = False) -> None:
        root.mkdir(parents=True, exist_ok=True)
        order = CryptoPaperOrder(
            order_id="crypto-paper-order-0001",
            symbol="BTCUSDT",
            side="BUY",
            requested_notional=10.0,
            requested_quantity=None,
            reference_price=100.0,
            status="PENDING",
            reason=None,
            created_at=self.as_of,
            metadata={"paper_only": True},
        )
        fill = CryptoPaperFill(
            fill_id="crypto-paper-fill-0001",
            order_id=order.order_id,
            symbol="BTCUSDT",
            side="BUY",
            quantity=0.1,
            fill_price=100.5,
            gross_notional=10.0,
            fee=0.1,
            slippage=0.05,
            net_notional=10.1,
            filled_at=self.as_of,
        )
        position = CryptoPaperPosition(
            symbol="BTCUSDT",
            quantity=0.1,
            avg_entry_price=100.0,
            realized_pnl=0.0,
            unrealized_pnl=0.2,
            last_price=last_price,
            updated_at=self.as_of,
        )
        snapshot = CryptoPaperPortfolioSnapshot(
            as_of=self.as_of,
            cash=89.9,
            equity=100.1,
            positions_value=10.2,
            realized_pnl=realized_pnl,
            unrealized_pnl=0.2,
            fees_paid=0.1,
            positions=[position],
            metadata={"quote_currency": "USDT"},
        )
        exit_events = []
        if with_exit:
            exit_events.append(
                CryptoPaperExitEvent(
                    exit_id="exit-1",
                    symbol="BTCUSDT",
                    position_quantity_before=0.1,
                    exit_quantity=0.1,
                    exit_reason="TAKE_PROFIT",
                    trigger_price=105.0,
                    fill_price=104.95,
                    gross_notional=10.495,
                    fee=0.01,
                    slippage=0.05,
                    realized_pnl=realized_pnl,
                    exited_at=self.as_of,
                    source="unit",
                )
            )
        execution_result = CryptoPaperExecutionResult(
            accepted_orders=[order],
            rejected_orders=[],
            fills=[fill],
            portfolio_snapshot=snapshot,
            exit_events=exit_events,
            metadata={"quote_currency": "USDT"},
        )
        (root / "crypto_paper_orders.json").write_text(json.dumps([order.to_dict()], ensure_ascii=False), encoding="utf-8")
        (root / "crypto_paper_fills.json").write_text(json.dumps([fill.to_dict()], ensure_ascii=False), encoding="utf-8")
        (root / "crypto_paper_positions.json").write_text(json.dumps([position.to_dict()], ensure_ascii=False), encoding="utf-8")
        (root / "crypto_paper_snapshot.json").write_text(json.dumps(snapshot.to_dict(), ensure_ascii=False), encoding="utf-8")
        (root / "crypto_paper_execution_result.json").write_text(json.dumps(execution_result.to_dict(), ensure_ascii=False), encoding="utf-8")
        if with_exit:
            (root / "crypto_paper_exit_events.json").write_text(json.dumps([event.to_dict() for event in exit_events], ensure_ascii=False), encoding="utf-8")

    def test_missing_artifacts_do_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = close_crypto_paper_day(
                artifacts_dir=Path(tmp),
                as_of=self.as_of,
                starting_cash=100.0,
            )
            self.assertTrue(result.warnings)
            self.assertEqual(result.performance.ending_equity, 100.0)

    def test_valid_snapshot_and_positions_produce_daily_close(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_artifacts(root)
            result = close_crypto_paper_day(artifacts_dir=root, as_of=self.as_of)
            self.assertEqual(result.performance.open_positions_count, 1)
            self.assertEqual(result.positions_marked[0].symbol, "BTCUSDT")

    def test_price_map_marks_positions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_artifacts(root, last_price=102.0)
            result = close_crypto_paper_day(
                artifacts_dir=root,
                as_of=self.as_of,
                price_map={"BTCUSDT": 105.0},
            )
            self.assertAlmostEqual(result.positions_marked[0].last_price, 105.0, places=6)
            self.assertGreater(result.performance.unrealized_pnl, 0.0)

    def test_missing_price_for_one_symbol_warns_and_continues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_artifacts(root, last_price=102.0)
            result = close_crypto_paper_day(artifacts_dir=root, as_of=self.as_of, price_map={})
            self.assertTrue(any("Missing latest price for BTCUSDT" in warning for warning in result.warnings))

    def test_provider_health_unhealthy_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_artifacts(root)
            result = close_crypto_paper_day(
                artifacts_dir=root,
                as_of=self.as_of,
                provider_health={"status": "unhealthy", "message": "provider down"},
            )
            self.assertEqual(result.provider_health["status"], "unhealthy")

    def test_artifacts_are_written_to_isolated_daily_close_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_artifacts(root)
            result = close_crypto_paper_day(artifacts_dir=root, as_of=self.as_of)
            daily_close_dir = root / "daily_close"
            self.assertTrue((daily_close_dir / "crypto_paper_daily_close.json").exists())
            self.assertTrue(result.artifacts_written)

    def test_existing_crypto_artifacts_are_not_destroyed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_artifacts(root)
            original = (root / "crypto_paper_snapshot.json").read_text(encoding="utf-8")
            close_crypto_paper_day(artifacts_dir=root, as_of=self.as_of)
            self.assertEqual((root / "crypto_paper_snapshot.json").read_text(encoding="utf-8"), original)

    def test_existing_equity_artifacts_are_not_touched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_artifacts(root)
            equity_artifact = root.parent / "paper.day_close.v1.0.0.json"
            equity_artifact.write_text("{}", encoding="utf-8")
            close_crypto_paper_day(artifacts_dir=root, as_of=self.as_of)
            self.assertEqual(equity_artifact.read_text(encoding="utf-8"), "{}")

    def test_markdown_report_is_generated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_artifacts(root)
            close_crypto_paper_day(artifacts_dir=root, as_of=self.as_of)
            report = (root / "daily_close" / "crypto_paper_daily_report.md").read_text(encoding="utf-8")
            self.assertIn("# Crypto Paper Daily Close", report)
            self.assertIn("Paper-only", report)

    def test_result_is_clearly_paper_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_artifacts(root)
            result = close_crypto_paper_day(artifacts_dir=root, as_of=self.as_of)
            self.assertTrue(result.paper_only)
            self.assertFalse(result.live_trading)

    def test_daily_close_includes_realized_pnl_after_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_artifacts(root, realized_pnl=1.25, with_exit=True)
            result = close_crypto_paper_day(artifacts_dir=root, as_of=self.as_of)
            self.assertAlmostEqual(result.performance.realized_pnl, 1.25, places=6)

    def test_daily_close_report_mentions_exits_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_artifacts(root, realized_pnl=1.25, with_exit=True)
            close_crypto_paper_day(artifacts_dir=root, as_of=self.as_of)
            report = (root / "daily_close" / "crypto_paper_daily_report.md").read_text(encoding="utf-8")
            self.assertIn("Exit events", report)


if __name__ == "__main__":
    unittest.main()
