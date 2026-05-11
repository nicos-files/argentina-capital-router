import sys
import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.execution.crypto_paper_exits import evaluate_crypto_exit_triggers
from src.execution.crypto_paper_models import CryptoPaperExecutionConfig, CryptoPaperPosition


class CryptoPaperExitsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.as_of = datetime(2026, 4, 24, 12, 0, 0)
        self.config = CryptoPaperExecutionConfig(enable_exits=True)

    def _position(self, qty=0.1, stop_loss=None, take_profit=None, updated_at=None):
        return CryptoPaperPosition(
            symbol="BTCUSDT",
            quantity=qty,
            avg_entry_price=100.0,
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            last_price=100.0,
            updated_at=updated_at,
            metadata={"stop_loss": stop_loss, "take_profit": take_profit, "avg_entry_price": 100.0},
        )

    def _candles(self, rows):
        return pd.DataFrame(rows)

    def test_position_with_no_stop_take_has_no_exit(self) -> None:
        events = evaluate_crypto_exit_triggers([self._position()], {"BTCUSDT": self._candles([])}, self.as_of, self.config)
        self.assertEqual(events, [])

    def test_candle_low_below_stop_loss_triggers_stop(self) -> None:
        events = evaluate_crypto_exit_triggers(
            [self._position(stop_loss=95.0)],
            {"BTCUSDT": self._candles([{"date": datetime(2026, 4, 24, 11, 0), "open": 100, "high": 101, "low": 94, "close": 95}])},
            self.as_of,
            self.config,
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].exit_reason, "STOP_LOSS")

    def test_candle_high_above_take_profit_triggers_take_profit(self) -> None:
        events = evaluate_crypto_exit_triggers(
            [self._position(take_profit=105.0)],
            {"BTCUSDT": self._candles([{"date": datetime(2026, 4, 24, 11, 0), "open": 100, "high": 106, "low": 99, "close": 105}])},
            self.as_of,
            self.config,
        )
        self.assertEqual(events[0].exit_reason, "TAKE_PROFIT")

    def test_same_candle_hits_both_stop_wins(self) -> None:
        events = evaluate_crypto_exit_triggers(
            [self._position(stop_loss=95.0, take_profit=105.0)],
            {"BTCUSDT": self._candles([{"date": datetime(2026, 4, 24, 11, 0), "open": 100, "high": 106, "low": 94, "close": 100}])},
            self.as_of,
            self.config,
        )
        self.assertEqual(events[0].exit_reason, "STOP_LOSS")
        self.assertTrue(events[0].metadata["same_candle_conflict"])

    def test_only_first_trigger_creates_exit(self) -> None:
        events = evaluate_crypto_exit_triggers(
            [self._position(take_profit=105.0)],
            {"BTCUSDT": self._candles([
                {"date": datetime(2026, 4, 24, 11, 0), "open": 100, "high": 106, "low": 99, "close": 105},
                {"date": datetime(2026, 4, 24, 11, 5), "open": 105, "high": 110, "low": 104, "close": 109},
            ])},
            self.as_of,
            self.config,
        )
        self.assertEqual(len(events), 1)

    def test_exit_is_full_quantity_by_default(self) -> None:
        events = evaluate_crypto_exit_triggers(
            [self._position(qty=0.25, take_profit=105.0)],
            {"BTCUSDT": self._candles([{"date": datetime(2026, 4, 24, 11, 0), "open": 100, "high": 106, "low": 99, "close": 105}])},
            self.as_of,
            self.config,
        )
        self.assertEqual(events[0].exit_quantity, 0.25)

    def test_zero_quantity_position_is_ignored(self) -> None:
        events = evaluate_crypto_exit_triggers(
            [self._position(qty=0.0, take_profit=105.0)],
            {"BTCUSDT": self._candles([{"date": datetime(2026, 4, 24, 11, 0), "open": 100, "high": 106, "low": 99, "close": 105}])},
            self.as_of,
            self.config,
        )
        self.assertEqual(events, [])

    def test_candles_are_evaluated_chronologically(self) -> None:
        events = evaluate_crypto_exit_triggers(
            [self._position(stop_loss=95.0, take_profit=105.0)],
            {"BTCUSDT": [
                {"date": datetime(2026, 4, 24, 11, 5), "open": 100, "high": 106, "low": 99, "close": 105},
                {"date": datetime(2026, 4, 24, 11, 0), "open": 100, "high": 101, "low": 94, "close": 95},
            ]},
            self.as_of,
            self.config,
        )
        self.assertEqual(events[0].exited_at, datetime(2026, 4, 24, 11, 0))

    def test_no_future_candles_before_entry_are_used(self) -> None:
        updated = datetime(2026, 4, 24, 11, 2)
        events = evaluate_crypto_exit_triggers(
            [self._position(stop_loss=95.0, updated_at=updated)],
            {"BTCUSDT": self._candles([
                {"date": datetime(2026, 4, 24, 11, 0), "open": 100, "high": 101, "low": 94, "close": 95},
                {"date": datetime(2026, 4, 24, 11, 5), "open": 100, "high": 101, "low": 94, "close": 95},
            ])},
            self.as_of,
            self.config,
        )
        self.assertEqual(events[0].exited_at, datetime(2026, 4, 24, 11, 5))

    def test_missing_candle_fields_are_handled_cleanly(self) -> None:
        events = evaluate_crypto_exit_triggers(
            [self._position(stop_loss=95.0)],
            {"BTCUSDT": [{"date": datetime(2026, 4, 24, 11, 0), "open": 100}]},
            self.as_of,
            self.config,
        )
        self.assertEqual(events, [])


class CryptoPaperExitsQuoteFallbackTests(unittest.TestCase):
    """Quote-based fallback when candle data is missing/incomplete or stale.

    The on-disk bug we fixed: an open BTCUSDT long had ``last_price`` already
    above ``take_profit`` but no exit was ever generated because the candle
    path only saw bars with ``high < take_profit``. Quote fallback closes that
    gap without enabling any live trading code path.
    """

    def setUp(self) -> None:
        self.as_of = datetime(2026, 5, 3, 17, 30, 0)
        self.config = CryptoPaperExecutionConfig(enable_exits=True)

    def _position(
        self,
        *,
        qty=0.001,
        avg_entry_price=76286.21896658644,
        last_price=78734.06,
        stop_loss=74840.444,
        take_profit=77131.478,
        updated_at=None,
    ):
        return CryptoPaperPosition(
            symbol="BTCUSDT",
            quantity=qty,
            avg_entry_price=avg_entry_price,
            realized_pnl=0.0,
            unrealized_pnl=0.0,
            last_price=last_price,
            updated_at=updated_at,
            metadata={
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "avg_entry_price": avg_entry_price,
            },
        )

    def test_long_above_take_profit_triggers_take_profit_via_quote_fallback(self):
        position = self._position()
        events = evaluate_crypto_exit_triggers(
            positions=[position],
            candles_by_symbol={},
            as_of=self.as_of,
            config=self.config,
            latest_quotes={"BTCUSDT": {"last_price": 78734.06, "bid": 78700.0, "ask": 78750.0}},
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].exit_reason, "TAKE_PROFIT")
        self.assertEqual(events[0].source, "stop_take_quote_fallback")
        self.assertEqual(events[0].trigger_price, 77131.478)
        self.assertEqual(events[0].metadata["fallback"], "quote")
        self.assertEqual(events[0].exit_quantity, position.quantity)

    def test_long_below_stop_loss_triggers_stop_loss_via_quote_fallback(self):
        events = evaluate_crypto_exit_triggers(
            positions=[self._position(last_price=70000.0)],
            candles_by_symbol={},
            as_of=self.as_of,
            config=self.config,
            latest_quotes={"BTCUSDT": {"last_price": 70000.0, "bid": 69990.0, "ask": 70010.0}},
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].exit_reason, "STOP_LOSS")
        self.assertEqual(events[0].source, "stop_take_quote_fallback")
        self.assertEqual(events[0].trigger_price, 74840.444)

    def test_quote_fallback_uses_position_last_price_when_quote_missing(self):
        events = evaluate_crypto_exit_triggers(
            positions=[self._position(last_price=78734.06)],
            candles_by_symbol={},
            as_of=self.as_of,
            config=self.config,
            latest_quotes={},
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].exit_reason, "TAKE_PROFIT")
        self.assertEqual(events[0].metadata["last_price"], 78734.06)

    def test_quote_fallback_does_not_fire_when_within_band(self):
        events = evaluate_crypto_exit_triggers(
            positions=[self._position(last_price=76500.0)],
            candles_by_symbol={},
            as_of=self.as_of,
            config=self.config,
            latest_quotes={"BTCUSDT": {"last_price": 76500.0, "bid": 76495.0, "ask": 76505.0}},
        )
        self.assertEqual(events, [])

    def test_take_profit_fallback_prefers_bid_over_last_price(self):
        # bid=77150 (>= TP 77131.478), last_price=77100 (< TP)
        # Bid-based check should still trigger TP because the conservative
        # sell-side price (bid) crossed the threshold.
        events = evaluate_crypto_exit_triggers(
            positions=[self._position(last_price=77100.0)],
            candles_by_symbol={},
            as_of=self.as_of,
            config=self.config,
            latest_quotes={"BTCUSDT": {"last_price": 77100.0, "bid": 77150.0, "ask": 77160.0}},
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].exit_reason, "TAKE_PROFIT")
        self.assertEqual(events[0].metadata["bid"], 77150.0)

    def test_candle_path_takes_precedence_over_quote_fallback(self):
        # Both candle (high above TP) AND quote (last_price above TP) trigger TP,
        # but the candle path runs first and its source is `stop_take_evaluator`.
        events = evaluate_crypto_exit_triggers(
            positions=[self._position(updated_at=datetime(2026, 5, 3, 10, 0))],
            candles_by_symbol={
                "BTCUSDT": [
                    {
                        "date": datetime(2026, 5, 3, 11, 0),
                        "open": 76500,
                        "high": 78000,
                        "low": 76400,
                        "close": 77500,
                    }
                ]
            },
            as_of=self.as_of,
            config=self.config,
            latest_quotes={"BTCUSDT": {"last_price": 78734.06, "bid": 78700.0}},
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].exit_reason, "TAKE_PROFIT")
        self.assertEqual(events[0].source, "stop_take_evaluator")

    def test_quote_fallback_same_tick_conflict_picks_stop_loss(self):
        # last_price below SL (stop_hit) AND bid above TP (take_hit, simulated
        # crossed market). Stop must win.
        events = evaluate_crypto_exit_triggers(
            positions=[self._position(last_price=70000.0)],
            candles_by_symbol={},
            as_of=self.as_of,
            config=self.config,
            latest_quotes={"BTCUSDT": {"last_price": 70000.0, "bid": 78000.0}},
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].exit_reason, "STOP_LOSS")
        self.assertTrue(events[0].metadata["same_tick_conflict"])

    def test_quote_fallback_with_only_stop_loss_configured(self):
        events = evaluate_crypto_exit_triggers(
            positions=[self._position(last_price=70000.0, take_profit=None)],
            candles_by_symbol={},
            as_of=self.as_of,
            config=self.config,
            latest_quotes={"BTCUSDT": {"last_price": 70000.0}},
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].exit_reason, "STOP_LOSS")

    def test_quote_fallback_with_only_take_profit_configured(self):
        events = evaluate_crypto_exit_triggers(
            positions=[self._position(last_price=78734.06, stop_loss=None)],
            candles_by_symbol={},
            as_of=self.as_of,
            config=self.config,
            latest_quotes={"BTCUSDT": {"last_price": 78734.06}},
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].exit_reason, "TAKE_PROFIT")

    def test_no_live_trading_code_path_in_exits_module(self):
        import inspect

        from src.execution import crypto_paper_exits as module

        source = inspect.getsource(module).lower()
        for needle in ("ccxt", "binance.client(", "live_trading=true", "broker_settings", "api_key", "api_secret"):
            self.assertNotIn(
                needle,
                source,
                f"crypto_paper_exits.py must not reference live trading: found {needle!r}",
            )

    def test_quote_fallback_signature_is_backward_compatible(self):
        # Existing callers (without latest_quotes) must keep working. Use an
        # in-band last_price so neither candle nor position-fallback triggers.
        events = evaluate_crypto_exit_triggers(
            positions=[self._position(last_price=76500.0)],
            candles_by_symbol={},
            as_of=self.as_of,
            config=self.config,
        )
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
