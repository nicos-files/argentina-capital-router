import unittest

from src.market_data.ar_providers import (
    ArgentinaBar,
    ArgentinaQuote,
    StaticArgentinaMarketDataProvider,
)
from src.market_data.ar_symbols import get_asset_by_symbol


class StaticProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.quote = ArgentinaQuote(
            symbol="GGAL",
            last_price=1234.5,
            currency="ARS",
            as_of="2026-05-12",
            source="static",
        )
        self.bars = {
            "GGAL": [
                ArgentinaBar("GGAL", "2026-05-01", 1.0, 1.1, 0.9, 1.05, 100.0),
                ArgentinaBar("GGAL", "2026-05-08", 1.0, 1.2, 0.95, 1.1, 120.0),
                ArgentinaBar("GGAL", "2026-05-15", 1.1, 1.3, 1.0, 1.2, 150.0),
            ]
        }
        self.provider = StaticArgentinaMarketDataProvider(
            quotes={"GGAL": self.quote}, bars=self.bars
        )

    def test_health_check(self) -> None:
        health = self.provider.health_check()
        self.assertTrue(health["ok"])
        self.assertTrue(health["read_only"])
        self.assertFalse(health["network_required"])
        self.assertFalse(health["live_trading_enabled"])
        self.assertEqual(health["quotes_loaded"], 1)
        self.assertEqual(health["bars_loaded"], 3)

    def test_supports_enabled_assets(self) -> None:
        ggal = get_asset_by_symbol("GGAL")
        self.assertIsNotNone(ggal)
        self.assertTrue(self.provider.supports(ggal))

    def test_quote_lookup(self) -> None:
        q = self.provider.get_latest_quote("ggal")
        self.assertEqual(q.last_price, 1234.5)

    def test_missing_quote_raises(self) -> None:
        with self.assertRaises(KeyError):
            self.provider.get_latest_quote("YPFD")

    def test_bars_basic(self) -> None:
        bars = self.provider.get_historical_bars("GGAL", timeframe="1d")
        self.assertEqual(len(bars), 3)

    def test_bars_date_filtering(self) -> None:
        bars = self.provider.get_historical_bars(
            "GGAL", timeframe="1d", start_date="2026-05-05", end_date="2026-05-10"
        )
        self.assertEqual(len(bars), 1)
        self.assertEqual(bars[0].date, "2026-05-08")

    def test_unsupported_timeframe_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.provider.get_historical_bars("GGAL", timeframe="5m")


if __name__ == "__main__":
    unittest.main()
