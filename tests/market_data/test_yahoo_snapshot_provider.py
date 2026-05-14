"""Tests for src/market_data/yahoo_snapshot_provider.py.

The transport is fully mocked - no real Yahoo HTTP call is ever made in
tests. ``_NetworkBlocker`` replaces ``socket.socket`` to guarantee that
any accidental fallthrough to the network would fail loudly.

Manual review only. No live trading. No broker automation. No orders.
"""
from __future__ import annotations

import socket
import unittest
from typing import Any, Mapping
from unittest.mock import MagicMock

from src.market_data.ar_symbols import ArgentinaAsset
from src.market_data.snapshot_providers import (
    MarketSnapshotRequest,
    YahooArgentinaMarketDataProvider,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _NetworkBlocker:
    def __enter__(self) -> "_NetworkBlocker":
        self._orig = socket.socket

        def _blocked(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError(
                "network access is forbidden in yahoo provider tests"
            )

        socket.socket = _blocked  # type: ignore[assignment]
        return self

    def __exit__(self, *exc_info: Any) -> None:
        socket.socket = self._orig  # type: ignore[assignment]


def _asset(symbol: str, *, asset_class: str = "argentina_equity", yahoo: str | None = None) -> ArgentinaAsset:
    return ArgentinaAsset(
        symbol=symbol,
        display_name=symbol,
        asset_class=asset_class,
        currency="ARS",
        market="BYMA",
        enabled=True,
        strategy_enabled=False,
        long_term_enabled=True,
        sector="financials",
        risk_bucket="medium",
        min_notional=0.0,
        notes="test",
        source_symbol_map={
            "internal": symbol,
            "yfinance": yahoo,
        },
    )


_TWO_ASSETS = [
    _asset("GGAL", yahoo="GGAL.BA"),
    _asset("YPFD", yahoo="YPFD.BA"),
]


def _stub_transport(payload: Mapping[str, Any]):
    """Return a transport callable that ignores the URL and returns ``payload``."""

    def _transport(url: str, timeout: float) -> Mapping[str, Any]:
        return payload

    return _transport


def _raising_transport(exc: BaseException):
    def _transport(url: str, timeout: float) -> Mapping[str, Any]:
        raise exc

    return _transport


_SUCCESSFUL_PAYLOAD = {
    "quoteResponse": {
        "result": [
            {
                "symbol": "GGAL.BA",
                "regularMarketPrice": 4520.5,
                "currency": "ARS",
            },
            {
                "symbol": "YPFD.BA",
                "regularMarketPrice": 12350.0,
                "currency": "ARS",
            },
        ],
        "error": None,
    }
}


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


class HealthCheckTests(unittest.TestCase):
    def test_no_api_key_required(self) -> None:
        provider = YahooArgentinaMarketDataProvider(
            assets=_TWO_ASSETS, transport=_stub_transport({})
        )
        health = provider.health_check()
        self.assertEqual(health["provider"], "yahoo")
        self.assertTrue(health["ok"])
        self.assertTrue(health["network_required"])
        self.assertFalse(health["requires_api_key"])
        self.assertTrue(health["read_only"])
        self.assertTrue(health["delayed"])
        self.assertEqual(health["coverage"], "best_effort")
        self.assertIn("free", health["notes"].lower())


# ---------------------------------------------------------------------------
# Symbol resolution + happy path
# ---------------------------------------------------------------------------


class SuccessPathTests(unittest.TestCase):
    def test_maps_internal_symbols_to_yahoo_symbols(self) -> None:
        captured: dict[str, Any] = {}

        def _transport(url: str, timeout: float) -> Mapping[str, Any]:
            captured["url"] = url
            return _SUCCESSFUL_PAYLOAD

        provider = YahooArgentinaMarketDataProvider(
            assets=_TWO_ASSETS, transport=_transport
        )
        with _NetworkBlocker():
            partial = provider.fetch(
                MarketSnapshotRequest(
                    as_of="2026-05-12", symbols=("GGAL", "YPFD")
                )
            )

        # URL contained the resolved Yahoo symbols, deduplicated/sorted.
        self.assertIn("GGAL.BA", captured["url"])
        self.assertIn("YPFD.BA", captured["url"])
        # Internal symbols are NOT used as the wire format.
        self.assertNotRegex(captured["url"], r"symbols=[^.]*\bGGAL\b(?!\.BA)")

        # Each asset is returned keyed by its internal symbol, with the
        # universe-derived asset_class and provider name preserved.
        self.assertIn("GGAL", partial.quotes)
        self.assertIn("YPFD", partial.quotes)
        ggal = partial.quotes["GGAL"]
        self.assertEqual(ggal.symbol, "GGAL")
        self.assertEqual(ggal.asset_class, "argentina_equity")
        self.assertEqual(ggal.price, 4520.5)
        self.assertEqual(ggal.currency, "ARS")
        self.assertEqual(ggal.provider, "yahoo")
        self.assertTrue(ggal.delayed)

    def test_no_fx_or_rates_served(self) -> None:
        provider = YahooArgentinaMarketDataProvider(
            assets=_TWO_ASSETS, transport=_stub_transport(_SUCCESSFUL_PAYLOAD)
        )
        with _NetworkBlocker():
            partial = provider.fetch(
                MarketSnapshotRequest(
                    as_of="2026-05-12",
                    symbols=("GGAL",),
                    fx_pairs=("USDARS_MEP",),
                    rate_keys=("money_market_monthly_pct",),
                )
            )
        self.assertEqual(dict(partial.fx_rates), {})
        self.assertEqual(dict(partial.rates), {})


# ---------------------------------------------------------------------------
# Graceful failure paths
# ---------------------------------------------------------------------------


class GracefulDegradationTests(unittest.TestCase):
    def test_unmapped_internal_symbol_is_reported_in_notes(self) -> None:
        provider = YahooArgentinaMarketDataProvider(
            assets=[_asset("ZZZZ", yahoo=None)],
            transport=_stub_transport(_SUCCESSFUL_PAYLOAD),
        )
        with _NetworkBlocker():
            partial = provider.fetch(
                MarketSnapshotRequest(
                    as_of="2026-05-12", symbols=("ZZZZ",)
                )
            )
        self.assertEqual(dict(partial.quotes), {})
        self.assertIn("unmapped", partial.notes)

    def test_http_error_returns_empty_with_warning(self) -> None:
        provider = YahooArgentinaMarketDataProvider(
            assets=_TWO_ASSETS,
            transport=_raising_transport(RuntimeError("HTTP 500")),
        )
        with _NetworkBlocker():
            partial = provider.fetch(
                MarketSnapshotRequest(
                    as_of="2026-05-12", symbols=("GGAL", "YPFD")
                )
            )
        self.assertEqual(dict(partial.quotes), {})
        self.assertIn("transport failed", partial.notes)
        # last_transport_error must surface in health_check but not raise.
        health = provider.health_check()
        self.assertEqual(health["last_transport_error"], "RuntimeError")

    def test_malformed_response_returns_empty(self) -> None:
        provider = YahooArgentinaMarketDataProvider(
            assets=_TWO_ASSETS,
            transport=_stub_transport("not-a-dict"),  # type: ignore[arg-type]
        )
        with _NetworkBlocker():
            partial = provider.fetch(
                MarketSnapshotRequest(
                    as_of="2026-05-12", symbols=("GGAL",)
                )
            )
        self.assertEqual(dict(partial.quotes), {})
        self.assertIn("transport failed", partial.notes)

    def test_partial_response_skips_unusable_quotes(self) -> None:
        payload = {
            "quoteResponse": {
                "result": [
                    {
                        "symbol": "GGAL.BA",
                        "regularMarketPrice": 4520.5,
                        "currency": "ARS",
                    },
                    {
                        # Yahoo sometimes returns the symbol with no price.
                        "symbol": "YPFD.BA",
                        "regularMarketPrice": None,
                    },
                ]
            }
        }
        provider = YahooArgentinaMarketDataProvider(
            assets=_TWO_ASSETS, transport=_stub_transport(payload)
        )
        with _NetworkBlocker():
            partial = provider.fetch(
                MarketSnapshotRequest(
                    as_of="2026-05-12", symbols=("GGAL", "YPFD")
                )
            )
        self.assertEqual(set(partial.quotes.keys()), {"GGAL"})
        # The note must mention which internal symbols had no usable price.
        self.assertIn("YPFD", partial.notes)

    def test_negative_price_is_rejected(self) -> None:
        payload = {
            "quoteResponse": {
                "result": [
                    {
                        "symbol": "GGAL.BA",
                        "regularMarketPrice": -1.0,
                    }
                ]
            }
        }
        provider = YahooArgentinaMarketDataProvider(
            assets=_TWO_ASSETS, transport=_stub_transport(payload)
        )
        with _NetworkBlocker():
            partial = provider.fetch(
                MarketSnapshotRequest(
                    as_of="2026-05-12", symbols=("GGAL",)
                )
            )
        self.assertEqual(dict(partial.quotes), {})

    def test_no_symbols_requested_short_circuits(self) -> None:
        transport = MagicMock(side_effect=AssertionError("must not be called"))
        provider = YahooArgentinaMarketDataProvider(
            assets=_TWO_ASSETS, transport=transport
        )
        with _NetworkBlocker():
            partial = provider.fetch(
                MarketSnapshotRequest(as_of="2026-05-12", symbols=())
            )
        self.assertEqual(dict(partial.quotes), {})
        transport.assert_not_called()


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------


class SafetyTests(unittest.TestCase):
    def test_no_api_key_substring_in_health_or_response(self) -> None:
        provider = YahooArgentinaMarketDataProvider(
            assets=_TWO_ASSETS,
            transport=_stub_transport(_SUCCESSFUL_PAYLOAD),
        )
        with _NetworkBlocker():
            partial = provider.fetch(
                MarketSnapshotRequest(
                    as_of="2026-05-12", symbols=("GGAL",)
                )
            )
        import json

        health = provider.health_check()
        blob = json.dumps(
            {"health": health, "notes": partial.notes}
        ).lower()
        for forbidden in ('"api_key"', '"apikey"', '"secret"', '"token"'):
            self.assertNotIn(forbidden, blob)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
