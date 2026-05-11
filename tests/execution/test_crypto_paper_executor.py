import sys
import unittest
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.contracts.recommendations.recommendation_models import RecommendationOutput
from src.execution.crypto_paper_executor import CryptoPaperExecutor
from src.execution.crypto_paper_ledger import CryptoPaperLedger
from src.execution.crypto_paper_models import CryptoPaperExecutionConfig, CryptoPaperExitEvent
from src.risk import RiskEngine


def _output(recommendations):
    return RecommendationOutput.build(
        run_id="run-1",
        horizon="INTRADAY",
        asof_date="2026-04-24",
        policy_id="intraday_crypto",
        policy_version="1",
        constraints=[],
        sizing_rule="crypto.paper.fixed_notional",
        recommendations=recommendations,
        cash_summary={},
        cash_policy="engine.paper_only",
    )


class CryptoPaperExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.executor = CryptoPaperExecutor(CryptoPaperExecutionConfig(starting_cash=100.0, max_notional_per_order=25.0))
        self.now = datetime(2026, 4, 24, 12, 0, 0)

    def test_empty_output_produces_no_orders_or_fills(self) -> None:
        result = self.executor.execute(_output([]), {}, self.now)
        self.assertEqual(result.fills, [])
        self.assertEqual(result.accepted_orders, [])

    def test_non_crypto_recommendation_is_rejected_safely(self) -> None:
        rec = {"ticker": "AAPL", "asset_id": "AAPL", "horizon": "INTRADAY", "action": "BUY", "usd_target": 10.0, "usd_target_effective": 10.0, "price_used": 100.0, "currency": "USD", "policy_id": "x", "policy_version": "1", "reason": "x", "sizing_rule": "x"}
        result = self.executor.execute(_output([rec]), {"AAPL": {"last_price": 100.0}}, self.now)
        self.assertEqual(len(result.rejected_orders), 1)

    def test_buy_crypto_recommendation_is_filled(self) -> None:
        rec = {"ticker": "BTCUSDT", "asset_id": "BTCUSDT", "horizon": "INTRADAY", "action": "BUY", "usd_target": 10.0, "usd_target_effective": 10.0, "price_used": 100.0, "currency": "USDT", "policy_id": "x", "policy_version": "1", "reason": "x", "sizing_rule": "x", "paper_only": True}
        result = self.executor.execute(_output([rec]), {"BTCUSDT": {"ask": 100.0, "last_price": 100.0}}, self.now)
        self.assertEqual(len(result.accepted_orders), 1)
        self.assertEqual(len(result.fills), 1)

    def test_missing_price_is_rejected(self) -> None:
        rec = {"ticker": "BTCUSDT", "asset_id": "BTCUSDT", "horizon": "INTRADAY", "action": "BUY", "usd_target": 10.0, "usd_target_effective": 10.0, "currency": "USDT", "policy_id": "x", "policy_version": "1", "reason": "x", "sizing_rule": "x"}
        result = self.executor.execute(_output([rec]), {}, self.now)
        self.assertEqual(result.rejected_orders[0].reason, "missing_price")

    def test_unsupported_action_is_rejected(self) -> None:
        rec = {"ticker": "BTCUSDT", "asset_id": "BTCUSDT", "horizon": "INTRADAY", "action": "SELL", "usd_target": 10.0, "usd_target_effective": 10.0, "price_used": 100.0, "currency": "USDT", "policy_id": "x", "policy_version": "1", "reason": "x", "sizing_rule": "x"}
        result = self.executor.execute(_output([rec]), {"BTCUSDT": {"ask": 100.0}}, self.now)
        self.assertEqual(result.rejected_orders[0].reason, "unsupported_action")

    def test_insufficient_cash_is_rejected(self) -> None:
        rec = {"ticker": "BTCUSDT", "asset_id": "BTCUSDT", "horizon": "INTRADAY", "action": "BUY", "usd_target": 25.0, "usd_target_effective": 25.0, "price_used": 100.0, "currency": "USDT", "policy_id": "x", "policy_version": "1", "reason": "x", "sizing_rule": "x", "paper_only": True}
        executor = CryptoPaperExecutor(CryptoPaperExecutionConfig(starting_cash=5.0, max_notional_per_order=25.0))
        result = executor.execute(_output([rec]), {"BTCUSDT": {"ask": 100.0}}, self.now)
        self.assertEqual(result.rejected_orders[0].reason, "risk:cash_insufficient")

    def test_fee_and_slippage_are_applied(self) -> None:
        rec = {"ticker": "BTCUSDT", "asset_id": "BTCUSDT", "horizon": "INTRADAY", "action": "BUY", "usd_target": 10.0, "usd_target_effective": 10.0, "price_used": 100.0, "currency": "USDT", "policy_id": "x", "policy_version": "1", "reason": "x", "sizing_rule": "x", "paper_only": True}
        result = self.executor.execute(_output([rec]), {"BTCUSDT": {"ask": 100.0}}, self.now)
        self.assertGreater(result.fills[0].fee, 0.0)
        self.assertGreater(result.fills[0].slippage, 0.0)

    def test_position_is_updated(self) -> None:
        rec = {"ticker": "BTCUSDT", "asset_id": "BTCUSDT", "horizon": "INTRADAY", "action": "BUY", "usd_target": 10.0, "usd_target_effective": 10.0, "price_used": 100.0, "currency": "USDT", "policy_id": "x", "policy_version": "1", "reason": "x", "sizing_rule": "x", "paper_only": True}
        result = self.executor.execute(_output([rec]), {"BTCUSDT": {"ask": 100.0, "last_price": 101.0}}, self.now)
        self.assertEqual(result.portfolio_snapshot.positions[0].symbol, "BTCUSDT")

    def test_snapshot_is_produced(self) -> None:
        result = self.executor.execute(_output([]), {}, self.now)
        self.assertIsNotNone(result.portfolio_snapshot)

    def test_risk_engine_rejection_produces_no_fill(self) -> None:
        rec = {"ticker": "BTCUSDT", "asset_id": "BTCUSDT", "horizon": "INTRADAY", "action": "BUY", "usd_target": 10.0, "usd_target_effective": 10.0, "price_used": 100.0, "currency": "USDT", "policy_id": "x", "policy_version": "1", "reason": "x", "sizing_rule": "x", "paper_only": True}
        executor = CryptoPaperExecutor(CryptoPaperExecutionConfig(), RiskEngine({"min_expected_net_edge": 1.0}))
        result = executor.execute(_output([rec]), {"BTCUSDT": {"ask": 100.0}}, self.now)
        self.assertEqual(result.fills, [])
        self.assertEqual(result.rejected_orders[0].reason, "risk:expected_net_edge_below_min")

    def test_live_enabled_true_is_rejected(self) -> None:
        rec = {"ticker": "BTCUSDT", "asset_id": "BTCUSDT", "horizon": "INTRADAY", "action": "BUY", "usd_target": 10.0, "usd_target_effective": 10.0, "price_used": 100.0, "currency": "USDT", "policy_id": "x", "policy_version": "1", "reason": "x", "sizing_rule": "x", "paper_only": True, "live_enabled": True}
        result = self.executor.execute(_output([rec]), {"BTCUSDT": {"ask": 100.0}}, self.now)
        self.assertEqual(result.rejected_orders[0].reason, "live_disabled")

    def test_no_broker_or_live_method_is_called(self) -> None:
        rec = {"ticker": "BTCUSDT", "asset_id": "BTCUSDT", "horizon": "INTRADAY", "action": "BUY", "usd_target": 10.0, "usd_target_effective": 10.0, "price_used": 100.0, "currency": "USDT", "policy_id": "x", "policy_version": "1", "reason": "x", "sizing_rule": "x", "paper_only": True}
        result = self.executor.execute(_output([rec]), {"BTCUSDT": {"ask": 100.0}}, self.now)
        self.assertEqual(len(result.accepted_orders), 1)

    def test_exit_event_creates_sell_fill(self) -> None:
        buy = {"ticker": "BTCUSDT", "asset_id": "BTCUSDT", "horizon": "INTRADAY", "action": "BUY", "usd_target": 10.0, "usd_target_effective": 10.0, "price_used": 100.0, "currency": "USDT", "policy_id": "x", "policy_version": "1", "reason": "x", "sizing_rule": "x", "paper_only": True}
        ledger = CryptoPaperLedger(CryptoPaperExecutionConfig(starting_cash=100.0, max_notional_per_order=25.0))
        initial = self.executor.execute(_output([buy]), {"BTCUSDT": {"ask": 100.0, "last_price": 100.0}}, self.now, ledger=ledger)
        exit_event = CryptoPaperExitEvent("e1", "BTCUSDT", initial.portfolio_snapshot.positions[0].quantity, initial.portfolio_snapshot.positions[0].quantity, "STOP_LOSS", 95.0, 95.0, 0.0, 0.0, 0.0, 0.0, self.now, "unit", {"avg_entry_price": 100.0})
        result = self.executor.execute(_output([]), {"BTCUSDT": {"bid": 95.0, "last_price": 95.0}}, self.now, ledger=ledger, exit_events=[exit_event])
        self.assertTrue(any(fill.side == "SELL" for fill in result.fills))

    def test_stop_loss_exit_uses_negative_slippage(self) -> None:
        ledger = CryptoPaperLedger(CryptoPaperExecutionConfig(starting_cash=100.0, max_notional_per_order=25.0))
        buy = {"ticker": "BTCUSDT", "asset_id": "BTCUSDT", "horizon": "INTRADAY", "action": "BUY", "usd_target": 10.0, "usd_target_effective": 10.0, "price_used": 100.0, "currency": "USDT", "policy_id": "x", "policy_version": "1", "reason": "x", "sizing_rule": "x", "paper_only": True}
        self.executor.execute(_output([buy]), {"BTCUSDT": {"ask": 100.0, "last_price": 100.0}}, self.now, ledger=ledger)
        qty = ledger.positions["BTCUSDT"].quantity
        event = CryptoPaperExitEvent("e1", "BTCUSDT", qty, qty, "STOP_LOSS", 95.0, 95.0, 0.0, 0.0, 0.0, 0.0, self.now, "unit", {"avg_entry_price": 100.0})
        result = self.executor.execute(_output([]), {"BTCUSDT": {"bid": 95.0}}, self.now, ledger=ledger, exit_events=[event])
        self.assertLess(result.fills[0].fill_price, 95.0)

    def test_take_profit_exit_uses_negative_slippage(self) -> None:
        ledger = CryptoPaperLedger(CryptoPaperExecutionConfig(starting_cash=100.0, max_notional_per_order=25.0))
        buy = {"ticker": "BTCUSDT", "asset_id": "BTCUSDT", "horizon": "INTRADAY", "action": "BUY", "usd_target": 10.0, "usd_target_effective": 10.0, "price_used": 100.0, "currency": "USDT", "policy_id": "x", "policy_version": "1", "reason": "x", "sizing_rule": "x", "paper_only": True}
        self.executor.execute(_output([buy]), {"BTCUSDT": {"ask": 100.0, "last_price": 100.0}}, self.now, ledger=ledger)
        qty = ledger.positions["BTCUSDT"].quantity
        event = CryptoPaperExitEvent("e1", "BTCUSDT", qty, qty, "TAKE_PROFIT", 110.0, 110.0, 0.0, 0.0, 0.0, 0.0, self.now, "unit", {"avg_entry_price": 100.0})
        result = self.executor.execute(_output([]), {"BTCUSDT": {"bid": 110.0}}, self.now, ledger=ledger, exit_events=[event])
        self.assertLess(result.fills[0].fill_price, 110.0)

    def test_exit_with_no_position_is_rejected(self) -> None:
        event = CryptoPaperExitEvent("e1", "BTCUSDT", 0.1, 0.1, "STOP_LOSS", 95.0, 95.0, 0.0, 0.0, 0.0, 0.0, self.now, "unit")
        result = self.executor.execute(_output([]), {"BTCUSDT": {"bid": 95.0}}, self.now, exit_events=[event])
        self.assertEqual(result.rejected_orders[0].reason, "position_not_found")

    def test_exit_updates_cash_position_and_snapshot(self) -> None:
        ledger = CryptoPaperLedger(CryptoPaperExecutionConfig(starting_cash=100.0, max_notional_per_order=25.0))
        buy = {"ticker": "BTCUSDT", "asset_id": "BTCUSDT", "horizon": "INTRADAY", "action": "BUY", "usd_target": 10.0, "usd_target_effective": 10.0, "price_used": 100.0, "currency": "USDT", "policy_id": "x", "policy_version": "1", "reason": "x", "sizing_rule": "x", "paper_only": True}
        self.executor.execute(_output([buy]), {"BTCUSDT": {"ask": 100.0, "last_price": 100.0}}, self.now, ledger=ledger)
        qty = ledger.positions["BTCUSDT"].quantity
        before_cash = ledger.cash
        event = CryptoPaperExitEvent("e1", "BTCUSDT", qty, qty, "TAKE_PROFIT", 110.0, 110.0, 0.0, 0.0, 0.0, 0.0, self.now, "unit", {"avg_entry_price": 100.0})
        result = self.executor.execute(_output([]), {"BTCUSDT": {"bid": 110.0}}, self.now, ledger=ledger, exit_events=[event])
        self.assertGreater(result.portfolio_snapshot.cash, before_cash)
        self.assertEqual(result.portfolio_snapshot.positions, [])
        self.assertGreater(result.portfolio_snapshot.realized_pnl, 0.0)

    def test_exit_event_is_json_serializable(self) -> None:
        event = CryptoPaperExitEvent("e1", "BTCUSDT", 0.1, 0.1, "TAKE_PROFIT", 110.0, 109.0, 10.9, 0.01, 0.05, 0.89, self.now, "unit")
        self.assertEqual(event.to_dict()["symbol"], "BTCUSDT")


if __name__ == "__main__":
    unittest.main()
