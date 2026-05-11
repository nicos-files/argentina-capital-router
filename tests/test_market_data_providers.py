import unittest
from unittest.mock import Mock, patch

import pandas as pd

from src.asset_universe import AssetDefinition
from src.market_data.providers import (
    AlphaVantagePriceProvider,
    YFinancePriceProvider,
    fetch_price_history_with_fallback,
)


class MarketDataProvidersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.us_asset = AssetDefinition(
            asset_id="AAPL.US",
            enabled=True,
            asset_class="EQUITY",
            market="US",
            currency="USD",
            lot_size=1,
            allow_fractional=True,
            yfinance_symbol="AAPL",
        )

    def test_yfinance_provider_normalizes_download(self) -> None:
        provider = YFinancePriceProvider()
        frame = pd.DataFrame(
            {
                "Open": [100.0],
                "High": [101.0],
                "Low": [99.0],
                "Close": [100.5],
                "Volume": [1000],
            },
            index=pd.to_datetime(["2026-04-21"]),
        )
        frame.index.name = "Date"
        with patch("src.market_data.providers.yf.download", return_value=frame):
            result = provider.fetch_price_history(self.us_asset, "2026-04-01")
        self.assertIsNotNone(result)
        self.assertEqual(list(result.columns), ["date", "ticker", "open", "high", "low", "close", "volume", "provider_symbol", "asset_class", "market"])
        self.assertEqual(result.iloc[0]["ticker"], "AAPL.US")

    def test_alpha_provider_supports_forex_and_us_only(self) -> None:
        provider = AlphaVantagePriceProvider()
        ba_asset = AssetDefinition(
            asset_id="GGAL.BA",
            enabled=True,
            asset_class="EQUITY",
            market="BA",
            currency="ARS",
            lot_size=1,
            allow_fractional=False,
            yfinance_symbol="GGAL.BA",
        )
        self.assertTrue(provider.supports(self.us_asset))
        self.assertFalse(provider.supports(ba_asset))

    def test_fetch_with_fallback_uses_second_provider(self) -> None:
        primary = Mock()
        primary.provider_name = "primary"
        primary.supports.return_value = True
        primary.fetch_price_history.return_value = None

        secondary = Mock()
        secondary.provider_name = "secondary"
        secondary.supports.return_value = True
        secondary.fetch_price_history.return_value = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-04-21"]),
                "ticker": ["AAPL.US"],
                "open": [1.0],
                "high": [1.0],
                "low": [1.0],
                "close": [1.0],
                "volume": [1.0],
                "provider_symbol": ["AAPL"],
                "asset_class": ["EQUITY"],
                "market": ["US"],
            }
        )

        name, frame = fetch_price_history_with_fallback(self.us_asset, "2026-04-01", [primary, secondary])
        self.assertEqual(name, "secondary")
        self.assertIsNotNone(frame)


if __name__ == "__main__":
    unittest.main()
