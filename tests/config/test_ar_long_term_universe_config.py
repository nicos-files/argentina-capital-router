import json
import unittest
from pathlib import Path

from src.market_data.ar_symbols import normalize_ar_symbol


REPO_ROOT = Path(__file__).resolve().parents[2]
UNIVERSE_PATH = REPO_ROOT / "config" / "market_universe" / "ar_long_term.json"


class ArLongTermUniverseConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = json.loads(UNIVERSE_PATH.read_text(encoding="utf-8"))

    def test_config_exists(self) -> None:
        self.assertTrue(UNIVERSE_PATH.exists())

    def test_top_level_fields_valid(self) -> None:
        for key in (
            "schema_version",
            "universe_id",
            "base_currency",
            "data_frequency",
            "execution_mode",
            "live_trading_enabled",
            "paper_trading_enabled",
            "assets",
        ):
            self.assertIn(key, self.data)
        self.assertEqual(self.data["universe_id"], "ar_long_term")
        self.assertEqual(self.data["base_currency"], "ARS")

    def test_manual_review_and_no_live_trading(self) -> None:
        self.assertEqual(self.data["execution_mode"], "manual_review_only")
        self.assertIs(self.data["live_trading_enabled"], False)
        self.assertIs(self.data["paper_trading_enabled"], False)

    def test_starter_symbols_present(self) -> None:
        symbols = {asset["symbol"] for asset in self.data["assets"]}
        for expected in ("GGAL", "YPFD", "PAMP", "ALUA", "TXAR", "COME", "MELI", "AAPL", "KO", "SPY"):
            self.assertIn(expected, symbols)

    def test_no_btc_or_eth(self) -> None:
        symbols = {asset["symbol"].upper() for asset in self.data["assets"]}
        self.assertNotIn("BTCUSDT", symbols)
        self.assertNotIn("ETHUSDT", symbols)

    def test_no_duplicate_normalized_symbols(self) -> None:
        normalized = [normalize_ar_symbol(asset["symbol"]) for asset in self.data["assets"]]
        self.assertEqual(len(normalized), len(set(normalized)))


if __name__ == "__main__":
    unittest.main()
