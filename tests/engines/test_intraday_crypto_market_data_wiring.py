import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.contracts.recommendations.recommendation_models import RecommendationOutput
from src.engines import EngineContext, IntradayCryptoEngine


class IntradayCryptoMarketDataWiringTests(unittest.TestCase):
    def test_no_config_is_safe_noop(self) -> None:
        engine = IntradayCryptoEngine()
        result = engine.run(
            EngineContext(
                as_of=datetime(2026, 4, 21, 12, 0, 0),
                run_id="20260421-1200",
                mode="test",
                universe=[],
            )
        )
        self.assertEqual(result.recommendations.to_payload()["recommendations"], [])
        self.assertTrue(any("No crypto universe configured" in warning for warning in result.diagnostics.warnings))

    def test_config_with_no_enabled_symbols_is_safe_noop(self) -> None:
        engine = IntradayCryptoEngine()
        result = engine.run(
            EngineContext(
                as_of=datetime(2026, 4, 21, 12, 0, 0),
                run_id="20260421-1200",
                mode="test",
                universe=[],
                config={
                    "crypto_universe": [{"symbol": "BTCUSDT", "enabled": False, "strategy_enabled": False}],
                    "crypto_strategy": {"enabled": True},
                },
            )
        )
        self.assertTrue(any("No enabled crypto symbols configured" in warning for warning in result.diagnostics.warnings))

    def test_enabled_symbols_with_strategy_disabled_is_noop_with_diagnostics(self) -> None:
        engine = IntradayCryptoEngine()
        result = engine.run(
            EngineContext(
                as_of=datetime(2026, 4, 21, 12, 0, 0),
                run_id="20260421-1200",
                mode="test",
                universe=["BTCUSDT", "ETHUSDT", "AAPL"],
                config={
                    "crypto_strategy": {"enabled": True},
                    "crypto_universe": [
                        {"symbol": "BTCUSDT", "enabled": True, "strategy_enabled": False},
                        {"symbol": "ETHUSDT", "enabled": True, "strategy_enabled": False},
                    ],
                },
            )
        )
        self.assertEqual(result.diagnostics.metadata["enabled_crypto_symbols"], ["BTCUSDT", "ETHUSDT"])
        self.assertEqual(result.diagnostics.metadata["strategy_enabled_count"], 0)
        self.assertTrue(any("No strategy-enabled crypto symbols" in warning for warning in result.diagnostics.warnings))

    def test_unhealthy_provider_does_not_crash(self) -> None:
        engine = IntradayCryptoEngine()
        provider = Mock()
        provider.get_historical_bars.return_value = pd.DataFrame()
        provider.get_latest_quote.return_value = {"last_price": 1.0}
        result = engine.run(
            EngineContext(
                as_of=datetime(2026, 4, 21, 12, 0, 0),
                run_id="20260421-1200",
                mode="test",
                universe=["BTCUSDT"],
                config={
                    "crypto_strategy": {"enabled": True},
                    "crypto_universe": [{"symbol": "BTCUSDT", "enabled": True, "strategy_enabled": True}],
                    "enable_crypto_market_data": True,
                },
                provider_health={"binance_spot": {"status": "unhealthy", "message": "down"}},
                metadata={"crypto_provider_name": "binance_spot", "crypto_provider": provider},
            )
        )
        self.assertEqual(result.recommendations.to_payload()["recommendations"], [])
        self.assertEqual(result.diagnostics.metadata["provider_name"], "binance_spot")
        self.assertTrue(any("provider unhealthy" in warning.lower() for warning in result.diagnostics.warnings))

    def test_strategy_enabled_but_provider_failure_is_safe_noop(self) -> None:
        engine = IntradayCryptoEngine()
        provider = Mock()
        provider.get_historical_bars.side_effect = RuntimeError("provider down")
        result = engine.run(
            EngineContext(
                as_of=datetime(2026, 4, 21, 12, 0, 0),
                run_id="20260421-1200",
                mode="test",
                universe=["BTCUSDT"],
                config={
                    "crypto_strategy": {"enabled": True},
                    "crypto_universe": [{"symbol": "BTCUSDT", "enabled": True, "strategy_enabled": True}],
                    "enable_crypto_market_data": True,
                },
                metadata={"crypto_provider_name": "binance_spot", "crypto_provider": provider},
            )
        )
        self.assertTrue(any("provider error" in warning.lower() or "failed for all" in warning.lower() for warning in result.diagnostics.warnings))

    def test_engine_never_creates_orders(self) -> None:
        engine = IntradayCryptoEngine()
        result = engine.run(
            EngineContext(
                as_of=datetime(2026, 4, 21, 12, 0, 0),
                run_id="20260421-1200",
                mode="test",
                universe=["BTCUSDT"],
                config={
                    "crypto_strategy": {"enabled": True},
                    "crypto_universe": [{"symbol": "BTCUSDT", "enabled": True, "strategy_enabled": True}],
                },
            )
        )
        self.assertIsInstance(result.recommendations, RecommendationOutput)
        self.assertEqual(result.recommendations.to_payload()["recommendations"], [])


if __name__ == "__main__":
    unittest.main()
