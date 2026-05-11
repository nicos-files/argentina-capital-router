import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.asset_universe import AssetDefinition
from src.market_data.providers import BinanceSpotMarketDataProvider, MarketDataProvider


class CryptoProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = BinanceSpotMarketDataProvider(base_url="https://example.test", timeout_seconds=5)
        self.asset = AssetDefinition(
            asset_id="BTCUSDT",
            enabled=True,
            asset_class="CRYPTO",
            market="CRYPTO",
            currency="USDT",
            lot_size=1,
            allow_fractional=True,
        )

    def test_provider_implements_market_data_provider_interface(self) -> None:
        self.assertIsInstance(self.provider, MarketDataProvider)

    def test_get_latest_quote_parses_mocked_binance_ticker(self) -> None:
        response = Mock()
        response.json.return_value = {
            "symbol": "BTCUSDT",
            "lastPrice": "65000.10",
            "bidPrice": "64999.90",
            "askPrice": "65000.20",
            "volume": "123.45",
            "quoteVolume": "8024691.00",
        }
        response.raise_for_status.return_value = None
        with patch("src.market_data.providers.requests.get", return_value=response):
            quote = self.provider.get_latest_quote("BTC/USDT")

        self.assertEqual(quote["provider"], "binance_spot")
        self.assertEqual(quote["symbol"], "BTCUSDT")
        self.assertEqual(quote["last_price"], 65000.10)
        self.assertEqual(quote["bid"], 64999.90)
        self.assertEqual(quote["ask"], 65000.20)

    def test_get_historical_bars_parses_mocked_klines(self) -> None:
        response = Mock()
        response.json.return_value = [
            [1713916860000, "65010.0", "65050.0", "64990.0", "65020.0", "12.0"],
            [1713916800000, "65000.0", "65020.0", "64980.0", "65010.0", "10.0"],
        ]
        response.raise_for_status.return_value = None
        with patch("src.market_data.providers.requests.get", return_value=response):
            bars = self.provider.get_historical_bars("BTCUSDT", "1m")

        self.assertEqual(list(bars["ticker"].unique()), ["BTCUSDT"])
        self.assertEqual(list(bars["date"]), sorted(list(bars["date"])))
        self.assertEqual(float(bars.iloc[0]["open"]), 65000.0)

    def test_fetch_price_history_delegates_to_daily_bars(self) -> None:
        frame = pd.DataFrame(
            {
                "date": pd.to_datetime(["2026-04-21"]),
                "ticker": ["BTCUSDT"],
                "open": [1.0],
                "high": [1.0],
                "low": [1.0],
                "close": [1.0],
                "volume": [1.0],
                "provider_symbol": ["BTCUSDT"],
                "asset_class": ["CRYPTO"],
                "market": ["CRYPTO"],
            }
        )
        with patch.object(self.provider, "get_historical_bars", return_value=frame) as mocked:
            result = self.provider.fetch_price_history(self.asset, "2026-04-01")

        mocked.assert_called_once()
        self.assertIsNotNone(result)

    def test_unsupported_timeframe_raises_clean_error(self) -> None:
        with self.assertRaises(ValueError):
            self.provider.get_historical_bars("BTCUSDT", "30s")

    def test_http_failure_marks_provider_unhealthy(self) -> None:
        with patch("src.market_data.providers.requests.get", side_effect=RuntimeError("boom")):
            health = self.provider.health_check()
        self.assertEqual(health.status, "unhealthy")

    def test_health_check_returns_healthy_on_valid_ping(self) -> None:
        response = Mock()
        response.json.return_value = {}
        response.raise_for_status.return_value = None
        with patch("src.market_data.providers.requests.get", return_value=response):
            health = self.provider.health_check()
        self.assertEqual(health.status, "healthy")

    def test_health_check_returns_unhealthy_on_invalid_response(self) -> None:
        response = Mock()
        response.json.return_value = []
        response.raise_for_status.return_value = None
        with patch("src.market_data.providers.requests.get", return_value=response):
            health = self.provider.health_check()
        self.assertEqual(health.status, "unhealthy")

    def test_no_api_key_is_required(self) -> None:
        self.assertFalse(hasattr(self.provider, "api_key"))

    def test_provider_has_no_order_methods(self) -> None:
        self.assertFalse(hasattr(self.provider, "place_order"))


if __name__ == "__main__":
    unittest.main()
