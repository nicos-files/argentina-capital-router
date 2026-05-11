import sys
import unittest
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.execution.crypto_paper_ledger import CryptoPaperLedger
from src.execution.crypto_paper_models import CryptoPaperExecutionConfig, CryptoPaperFill


class CryptoPaperLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = CryptoPaperLedger(CryptoPaperExecutionConfig(starting_cash=100.0))

    def _fill(self, qty=0.1, price=100.0, gross=10.0, fee=0.1):
        return CryptoPaperFill(
            fill_id="f1",
            order_id="o1",
            symbol="BTCUSDT",
            side="BUY",
            quantity=qty,
            fill_price=price,
            gross_notional=gross,
            fee=fee,
            slippage=0.05,
            net_notional=gross + fee,
            filled_at=datetime.utcnow(),
        )

    def _sell_fill(self, qty=0.05, price=110.0, gross=5.5, fee=0.05):
        return CryptoPaperFill(
            fill_id="s1",
            order_id="o2",
            symbol="BTCUSDT",
            side="SELL",
            quantity=qty,
            fill_price=price,
            gross_notional=gross,
            fee=fee,
            slippage=0.05,
            net_notional=gross - fee,
            filled_at=datetime.utcnow(),
        )

    def test_starting_cash_initializes_correctly(self) -> None:
        self.assertEqual(self.ledger.cash, 100.0)

    def test_buy_fill_creates_new_position(self) -> None:
        self.ledger.apply_buy_fill(self._fill())
        self.assertIn("BTCUSDT", self.ledger.positions)

    def test_buy_fill_updates_cash(self) -> None:
        self.ledger.apply_buy_fill(self._fill())
        self.assertAlmostEqual(self.ledger.cash, 89.9, places=6)

    def test_buy_fill_updates_avg_entry_price(self) -> None:
        self.ledger.apply_buy_fill(self._fill(price=100.0, gross=10.0, fee=0.1))
        self.assertAlmostEqual(self.ledger.positions["BTCUSDT"].avg_entry_price, 100.0, places=6)

    def test_second_buy_updates_weighted_avg_entry(self) -> None:
        self.ledger.apply_buy_fill(self._fill(qty=0.1, price=100.0, gross=10.0, fee=0.1))
        self.ledger.apply_buy_fill(self._fill(qty=0.1, price=110.0, gross=11.0, fee=0.11))
        self.assertAlmostEqual(self.ledger.positions["BTCUSDT"].avg_entry_price, 105.0, places=6)

    def test_fees_are_tracked(self) -> None:
        self.ledger.apply_buy_fill(self._fill(fee=0.2))
        self.assertAlmostEqual(self.ledger.fees_paid, 0.2, places=6)

    def test_snapshot_includes_pnl_and_values(self) -> None:
        self.ledger.apply_buy_fill(self._fill())
        self.ledger.mark_to_market({"BTCUSDT": 105.0}, datetime.utcnow())
        snapshot = self.ledger.snapshot(datetime.utcnow())
        self.assertGreater(snapshot.equity, 0)
        self.assertEqual(len(snapshot.positions), 1)

    def test_mark_to_market_updates_unrealized_pnl(self) -> None:
        self.ledger.apply_buy_fill(self._fill())
        self.ledger.mark_to_market({"BTCUSDT": 105.0}, datetime.utcnow())
        self.assertGreater(self.ledger.positions["BTCUSDT"].unrealized_pnl, 0)

    def test_insufficient_cash_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.ledger.apply_buy_fill(self._fill(gross=200.0, fee=1.0))

    def test_no_short_behavior_exists_by_default(self) -> None:
        self.assertFalse(self.ledger.config.allow_short)

    def test_sell_without_position_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.ledger.apply_sell_fill(self._sell_fill())

    def test_sell_more_than_position_is_rejected(self) -> None:
        self.ledger.apply_buy_fill(self._fill(qty=0.1))
        with self.assertRaises(ValueError):
            self.ledger.apply_sell_fill(self._sell_fill(qty=0.2, gross=22.0))

    def test_sell_reduces_position_quantity(self) -> None:
        self.ledger.apply_buy_fill(self._fill(qty=0.1))
        self.ledger.apply_sell_fill(self._sell_fill(qty=0.05, gross=5.5))
        self.assertAlmostEqual(self.ledger.positions["BTCUSDT"].quantity, 0.05, places=6)

    def test_sell_increases_cash_net_of_fees(self) -> None:
        self.ledger.apply_buy_fill(self._fill(qty=0.1))
        before = self.ledger.cash
        self.ledger.apply_sell_fill(self._sell_fill(qty=0.05, gross=5.5, fee=0.05))
        self.assertAlmostEqual(self.ledger.cash, before + 5.5 - 0.05, places=6)

    def test_sell_calculates_realized_pnl_correctly(self) -> None:
        self.ledger.apply_buy_fill(self._fill(qty=0.1, price=100.0, gross=10.0, fee=0.1))
        self.ledger.apply_sell_fill(self._sell_fill(qty=0.05, price=110.0, gross=5.5, fee=0.05))
        self.assertAlmostEqual(self.ledger.realized_pnl, (110.0 - 100.0) * 0.05 - 0.05, places=6)

    def test_sell_tracks_fees(self) -> None:
        self.ledger.apply_buy_fill(self._fill(fee=0.1))
        self.ledger.apply_sell_fill(self._sell_fill(fee=0.05))
        self.assertAlmostEqual(self.ledger.fees_paid, 0.15, places=6)

    def test_full_sell_removes_open_position(self) -> None:
        self.ledger.apply_buy_fill(self._fill(qty=0.1))
        self.ledger.apply_sell_fill(self._sell_fill(qty=0.1, gross=11.0))
        self.assertNotIn("BTCUSDT", self.ledger.positions)

    def test_partial_sell_keeps_avg_entry_price(self) -> None:
        self.ledger.apply_buy_fill(self._fill(qty=0.1, price=100.0, gross=10.0, fee=0.1))
        self.ledger.apply_sell_fill(self._sell_fill(qty=0.05, price=110.0, gross=5.5, fee=0.05))
        self.assertAlmostEqual(self.ledger.positions["BTCUSDT"].avg_entry_price, 100.0, places=6)

    def test_snapshot_reflects_realized_pnl(self) -> None:
        self.ledger.apply_buy_fill(self._fill(qty=0.1, price=100.0, gross=10.0, fee=0.1))
        self.ledger.apply_sell_fill(self._sell_fill(qty=0.05, price=110.0, gross=5.5, fee=0.05))
        snapshot = self.ledger.snapshot(datetime.utcnow())
        self.assertGreater(snapshot.realized_pnl, 0.0)


if __name__ == "__main__":
    unittest.main()
