import sys
import unittest
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.strategies import IntradayCryptoBaselineStrategy


def _candles(closes, volumes=None):
    volumes = volumes or [10.0] * len(closes)
    return pd.DataFrame(
        {
            "date": pd.date_range("2026-04-24 10:00:00", periods=len(closes), freq="5min"),
            "close": closes,
            "volume": volumes,
        }
    )


class CryptoIntradayBaselineStrategyTests(unittest.TestCase):
    def test_not_enough_candles_returns_no_trade(self) -> None:
        strategy = IntradayCryptoBaselineStrategy()
        signal = strategy.evaluate("BTCUSDT", _candles([1.0] * 10), {"last_price": 1.0})
        self.assertIsNone(signal)

    def test_invalid_latest_price_returns_no_trade(self) -> None:
        strategy = IntradayCryptoBaselineStrategy()
        signal = strategy.evaluate("BTCUSDT", _candles([1.0] * 30), {"last_price": "bad"})
        self.assertIsNone(signal)

    def test_fast_ma_above_slow_ma_with_positive_recent_return_returns_buy(self) -> None:
        strategy = IntradayCryptoBaselineStrategy()
        closes = [100.0 + (i * 0.2) for i in range(30)]
        signal = strategy.evaluate("BTCUSDT", _candles(closes), {"last_price": closes[-1]})
        self.assertIsNotNone(signal)
        self.assertEqual(signal.action, "BUY")

    def test_fast_ma_below_slow_ma_returns_no_trade(self) -> None:
        strategy = IntradayCryptoBaselineStrategy()
        closes = [100.0 - (i * 0.2) for i in range(30)]
        signal = strategy.evaluate("BTCUSDT", _candles(closes), {"last_price": closes[-1]})
        self.assertIsNone(signal)

    def test_signal_strength_below_threshold_returns_no_trade(self) -> None:
        strategy = IntradayCryptoBaselineStrategy({"min_abs_signal_strength": 0.01})
        closes = [100.0 + (i * 0.01) for i in range(30)]
        signal = strategy.evaluate("BTCUSDT", _candles(closes), {"last_price": closes[-1]})
        self.assertIsNone(signal)

    def test_volatility_above_max_returns_no_trade(self) -> None:
        strategy = IntradayCryptoBaselineStrategy({"max_volatility_pct": 0.01})
        closes = [100, 110, 90, 112, 88, 115, 87, 116, 86, 117, 85, 118, 84, 119, 83, 120, 82, 121, 81, 122, 80, 123]
        signal = strategy.evaluate("BTCUSDT", _candles(closes), {"last_price": closes[-1]})
        self.assertIsNone(signal)

    def test_buy_candidate_includes_entry_stop_take_profit_and_notional(self) -> None:
        strategy = IntradayCryptoBaselineStrategy()
        closes = [100.0 + (i * 0.2) for i in range(30)]
        signal = strategy.evaluate("BTCUSDT", _candles(closes), {"last_price": closes[-1]})
        self.assertIsNotNone(signal)
        self.assertIsNotNone(signal.entry_price)
        self.assertIsNotNone(signal.stop_loss)
        self.assertIsNotNone(signal.take_profit)
        self.assertEqual(signal.max_notional, 25.0)

    def test_allow_short_false_prevents_short_signal(self) -> None:
        strategy = IntradayCryptoBaselineStrategy({"allow_short": False})
        closes = [100.0 - (i * 0.2) for i in range(30)]
        signal = strategy.evaluate("BTCUSDT", _candles(closes), {"last_price": closes[-1]})
        self.assertIsNone(signal)

    def test_output_is_deterministic_for_fixed_candles(self) -> None:
        strategy = IntradayCryptoBaselineStrategy()
        closes = [100.0 + (i * 0.2) for i in range(30)]
        first = strategy.evaluate("BTCUSDT", _candles(closes), {"last_price": closes[-1]})
        second = strategy.evaluate("BTCUSDT", _candles(closes), {"last_price": closes[-1]})
        self.assertEqual(first, second)

    def test_provider_unhealthy_returns_no_trade(self) -> None:
        strategy = IntradayCryptoBaselineStrategy()
        closes = [100.0 + (i * 0.2) for i in range(30)]
        signal = strategy.evaluate("BTCUSDT", _candles(closes), {"last_price": closes[-1]}, provider_healthy=False)
        self.assertIsNone(signal)


if __name__ == "__main__":
    unittest.main()
