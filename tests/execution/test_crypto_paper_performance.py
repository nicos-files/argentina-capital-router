import json
import sys
import unittest
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.execution.crypto_paper_models import CryptoPaperPortfolioSnapshot, CryptoPaperPosition
from src.execution.crypto_paper_performance import compute_crypto_paper_performance


class CryptoPaperPerformanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.as_of = datetime(2026, 4, 24, 18, 0, 0)

    def _position(self, last_price=105.0, avg_entry=100.0, qty=0.1, unrealized=0.5):
        return CryptoPaperPosition(
            symbol="BTCUSDT",
            quantity=qty,
            avg_entry_price=avg_entry,
            realized_pnl=0.0,
            unrealized_pnl=unrealized,
            last_price=last_price,
            updated_at=self.as_of,
        )

    def test_empty_state_produces_zeroish_performance_with_warning(self) -> None:
        summary = compute_crypto_paper_performance(
            as_of=self.as_of,
            positions=[],
            ending_cash=100.0,
            starting_cash=100.0,
            warnings=["missing artifacts"],
        )
        self.assertEqual(summary.total_pnl, 0.0)
        self.assertIn("missing artifacts", summary.data_quality_warnings)

    def test_starting_cash_only_keeps_equity_equal_to_cash(self) -> None:
        summary = compute_crypto_paper_performance(
            as_of=self.as_of,
            positions=[],
            ending_cash=100.0,
            starting_cash=100.0,
        )
        self.assertEqual(summary.starting_equity, 100.0)
        self.assertEqual(summary.ending_equity, 100.0)

    def test_open_buy_marked_above_avg_entry_is_positive(self) -> None:
        summary = compute_crypto_paper_performance(
            as_of=self.as_of,
            positions=[self._position(last_price=110.0, unrealized=1.0)],
            ending_cash=89.9,
            current_snapshot=CryptoPaperPortfolioSnapshot(
                as_of=self.as_of,
                cash=89.9,
                equity=100.9,
                positions_value=11.0,
                realized_pnl=0.0,
                unrealized_pnl=1.0,
                fees_paid=0.1,
                positions=[self._position(last_price=110.0, unrealized=1.0)],
            ),
            starting_cash=100.0,
        )
        self.assertGreater(summary.unrealized_pnl, 0.0)

    def test_open_buy_marked_below_avg_entry_is_negative(self) -> None:
        position = self._position(last_price=95.0, unrealized=-0.5)
        summary = compute_crypto_paper_performance(
            as_of=self.as_of,
            positions=[position],
            ending_cash=89.9,
            current_snapshot=CryptoPaperPortfolioSnapshot(
                as_of=self.as_of,
                cash=89.9,
                equity=99.4,
                positions_value=9.5,
                realized_pnl=0.0,
                unrealized_pnl=-0.5,
                fees_paid=0.1,
                positions=[position],
            ),
            starting_cash=100.0,
        )
        self.assertLess(summary.unrealized_pnl, 0.0)

    def test_fees_are_reflected_from_snapshot(self) -> None:
        position = self._position()
        snapshot = CryptoPaperPortfolioSnapshot(
            as_of=self.as_of,
            cash=89.9,
            equity=100.4,
            positions_value=10.5,
            realized_pnl=0.0,
            unrealized_pnl=0.5,
            fees_paid=0.1,
            positions=[position],
        )
        summary = compute_crypto_paper_performance(
            as_of=self.as_of,
            positions=[position],
            ending_cash=89.9,
            current_snapshot=snapshot,
            starting_cash=100.0,
        )
        self.assertEqual(summary.fees_paid, 0.1)

    def test_total_return_pct_is_calculated_correctly(self) -> None:
        summary = compute_crypto_paper_performance(
            as_of=self.as_of,
            positions=[],
            ending_cash=110.0,
            starting_cash=100.0,
        )
        self.assertAlmostEqual(summary.total_return_pct, 0.1, places=6)

    def test_best_and_worst_positions_are_identified(self) -> None:
        good = CryptoPaperPosition("BTCUSDT", 0.1, 100.0, 0.0, 1.0, 110.0, self.as_of)
        bad = CryptoPaperPosition("ETHUSDT", 0.2, 100.0, 0.0, -2.0, 90.0, self.as_of)
        summary = compute_crypto_paper_performance(
            as_of=self.as_of,
            positions=[good, bad],
            ending_cash=50.0,
            starting_cash=100.0,
        )
        self.assertEqual(summary.best_position["symbol"], "BTCUSDT")
        self.assertEqual(summary.worst_position["symbol"], "ETHUSDT")

    def test_missing_latest_price_can_use_last_known_price(self) -> None:
        position = CryptoPaperPosition("BTCUSDT", 0.1, 100.0, 0.0, 0.2, 102.0, self.as_of)
        summary = compute_crypto_paper_performance(
            as_of=self.as_of,
            positions=[position],
            ending_cash=89.9,
            starting_cash=100.0,
            warnings=["used last known price"],
        )
        self.assertIn("used last known price", summary.data_quality_warnings)

    def test_no_realized_pnl_is_invented_without_sells(self) -> None:
        summary = compute_crypto_paper_performance(
            as_of=self.as_of,
            positions=[self._position()],
            ending_cash=89.9,
            starting_cash=100.0,
        )
        self.assertEqual(summary.realized_pnl, 0.0)

    def test_summary_is_json_serializable(self) -> None:
        summary = compute_crypto_paper_performance(
            as_of=self.as_of,
            positions=[],
            ending_cash=100.0,
            starting_cash=100.0,
        )
        json.dumps(summary.to_dict())


if __name__ == "__main__":
    unittest.main()
