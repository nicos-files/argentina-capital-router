import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.market_data.crypto_symbols import (
    enabled_crypto_symbols,
    is_crypto_symbol,
    load_crypto_universe,
    normalize_crypto_symbol,
)


class CryptoSymbolsTests(unittest.TestCase):
    def test_btc_slash_usdt_normalizes_to_binance_symbol(self) -> None:
        self.assertEqual(normalize_crypto_symbol("BTC/USDT"), "BTCUSDT")

    def test_btc_dash_usdt_normalizes_to_binance_symbol(self) -> None:
        self.assertEqual(normalize_crypto_symbol("BTC-USDT"), "BTCUSDT")

    def test_lowercase_symbol_normalizes(self) -> None:
        self.assertEqual(normalize_crypto_symbol("btcusdt"), "BTCUSDT")

    def test_eth_slash_usdt_normalizes(self) -> None:
        self.assertEqual(normalize_crypto_symbol("ETH/USDT"), "ETHUSDT")

    def test_aapl_is_not_crypto(self) -> None:
        self.assertFalse(is_crypto_symbol("AAPL"))

    def test_ggal_is_not_crypto(self) -> None:
        self.assertFalse(is_crypto_symbol("GGAL"))

    def test_btc_is_crypto_by_known_base_rule(self) -> None:
        self.assertTrue(is_crypto_symbol("BTC"))

    def test_enabled_crypto_symbols_returns_only_enabled(self) -> None:
        config = {
            "symbols": [
                {"symbol": "BTCUSDT", "enabled": True},
                {"symbol": "ETHUSDT", "enabled": False},
            ]
        }
        self.assertEqual(enabled_crypto_symbols(config), ["BTCUSDT"])

    def test_disabled_symbols_are_excluded(self) -> None:
        config = {
            "symbols": [
                {"symbol": "BTCUSDT", "enabled": False},
                {"symbol": "ETHUSDT", "enabled": False},
            ]
        }
        self.assertEqual(enabled_crypto_symbols(config), [])

    def test_malformed_config_is_handled_cleanly(self) -> None:
        target = REPO_ROOT / "config" / "market_universe" / "missing.crypto.json"
        self.assertEqual(load_crypto_universe(target), [])


if __name__ == "__main__":
    unittest.main()
