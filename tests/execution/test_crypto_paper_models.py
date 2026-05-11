import json
import sys
import unittest
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.execution.crypto_paper_models import (
    CryptoPaperExecutionConfig,
    CryptoPaperExitEvent,
    CryptoPaperFill,
    CryptoPaperOrder,
    CryptoPaperPortfolioSnapshot,
    CryptoPaperPosition,
)


class CryptoPaperModelsTests(unittest.TestCase):
    def test_models_are_constructible(self) -> None:
        order = CryptoPaperOrder("o1", "BTCUSDT", "BUY", 10.0, None, 100.0, "PENDING", None, datetime.utcnow())
        fill = CryptoPaperFill("f1", "o1", "BTCUSDT", "BUY", 0.1, 100.0, 10.0, 0.1, 0.05, 10.1, datetime.utcnow())
        exit_event = CryptoPaperExitEvent("e1", "BTCUSDT", 0.1, 0.1, "TAKE_PROFIT", 105.0, 104.95, 10.495, 0.01, 0.05, 0.49, datetime.utcnow(), "unit")
        position = CryptoPaperPosition("BTCUSDT", 0.1, 100.0, 0.0, 0.0, 101.0, datetime.utcnow())
        snapshot = CryptoPaperPortfolioSnapshot(datetime.utcnow(), 90.0, 100.0, 10.0, 0.0, 1.0, 0.1, [position])
        self.assertEqual(order.symbol, "BTCUSDT")
        self.assertEqual(fill.order_id, "o1")
        self.assertEqual(exit_event.exit_reason, "TAKE_PROFIT")
        self.assertEqual(snapshot.positions[0].symbol, "BTCUSDT")

    def test_models_serialize_to_json(self) -> None:
        order = CryptoPaperOrder("o1", "BTCUSDT", "BUY", 10.0, None, 100.0, "PENDING", None, datetime.utcnow())
        payload = order.to_dict()
        json.dumps(payload)
        self.assertEqual(payload["symbol"], "BTCUSDT")

    def test_defaults_are_safe(self) -> None:
        config = CryptoPaperExecutionConfig()
        self.assertEqual(config.starting_cash, 100.0)
        self.assertFalse(config.allow_short)
        self.assertFalse(config.enable_exits)

    def test_allow_live_trading_defaults_to_false(self) -> None:
        config = CryptoPaperExecutionConfig()
        self.assertFalse(config.allow_live_trading)


if __name__ == "__main__":
    unittest.main()
