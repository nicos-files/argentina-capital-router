"""Tests for src/market_data/snapshot_providers.py.

Manual review only. No network. No broker. No live trading.
No real API keys are used or asserted on.
"""
from __future__ import annotations

import json
import socket
import tempfile
import unittest
from pathlib import Path
from typing import Any

from src.market_data.manual_snapshot import (
    FxRate,
    ManualQuote,
    RateInput,
)
from src.market_data.snapshot_providers import (
    AssembledMarketSnapshot,
    ManualFileSnapshotProvider,
    MarketSnapshotProvider,
    MarketSnapshotRequest,
    PartialMarketSnapshot,
    StaticExampleSnapshotProvider,
    assemble_market_snapshot,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_MARKET = (
    REPO_ROOT / "config" / "data_inputs" / "manual_market_snapshot.example.json"
)


def _block_network() -> "_NetworkBlocker":
    """Return a context manager that fails if any code opens a real socket."""
    return _NetworkBlocker()


class _NetworkBlocker:
    def __enter__(self) -> "_NetworkBlocker":
        self._orig_socket = socket.socket

        def _blocked(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError(
                "network access is forbidden in market_data tests"
            )

        socket.socket = _blocked  # type: ignore[assignment]
        return self

    def __exit__(self, *exc_info: Any) -> None:
        socket.socket = self._orig_socket  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Request dataclass
# ---------------------------------------------------------------------------


class MarketSnapshotRequestTests(unittest.TestCase):
    def test_normalizes_and_dedupes_symbols_and_pairs(self) -> None:
        request = MarketSnapshotRequest(
            as_of="2026-05-12",
            symbols=("ggal", "GGAL", "spy"),
            fx_pairs=("usd/ars mep", "USDARS_MEP"),
            rate_keys=("k1", "k1", "k2"),
        )
        self.assertEqual(request.symbols, ("GGAL", "SPY"))
        self.assertEqual(request.fx_pairs, ("USD_ARS_MEP", "USDARS_MEP"))
        self.assertEqual(request.rate_keys, ("k1", "k2"))


# ---------------------------------------------------------------------------
# Static example provider
# ---------------------------------------------------------------------------


class StaticExampleSnapshotProviderTests(unittest.TestCase):
    def test_serves_requested_default_universe(self) -> None:
        provider = StaticExampleSnapshotProvider()
        request = MarketSnapshotRequest(
            as_of="2026-05-12",
            symbols=("SPY", "GGAL", "AAPL"),
            fx_pairs=("USDARS_MEP",),
            rate_keys=("money_market_monthly_pct",),
        )
        with _block_network():
            partial = provider.fetch(request)

        self.assertEqual(partial.provider_name, "static_example")
        self.assertEqual(
            set(partial.quotes.keys()), {"SPY", "GGAL", "AAPL"}
        )
        self.assertIn("USDARS_MEP", partial.fx_rates)
        self.assertIn("money_market_monthly_pct", partial.rates)
        for quote in partial.quotes.values():
            self.assertEqual(quote.provider, "static_example")
            self.assertTrue(quote.delayed)
            self.assertGreater(quote.price, 1.0)
        self.assertGreater(partial.fx_rates["USDARS_MEP"].rate, 1.0)

    def test_unknown_symbol_returns_subset(self) -> None:
        provider = StaticExampleSnapshotProvider()
        request = MarketSnapshotRequest(
            as_of="2026-05-12",
            symbols=("SPY", "FAKECORP"),
            fx_pairs=(),
            rate_keys=(),
        )
        partial = provider.fetch(request)
        self.assertEqual(set(partial.quotes.keys()), {"SPY"})

    def test_custom_payload_overrides_defaults(self) -> None:
        provider = StaticExampleSnapshotProvider(
            quotes={
                "spy": ManualQuote(
                    symbol="SPY",
                    asset_class="cedear",
                    price=12345.0,
                    currency="ARS",
                    as_of="2026-05-12",
                    provider="custom_static",
                )
            },
            fx_rates={
                "usdars mep": FxRate(
                    pair="USDARS_MEP",
                    rate=1500.0,
                    as_of="2026-05-12",
                    provider="custom_static",
                )
            },
            rates={
                "k1": RateInput(
                    key="k1",
                    value=4.2,
                    as_of="2026-05-12",
                    provider="custom_static",
                )
            },
        )
        partial = provider.fetch(
            MarketSnapshotRequest(
                as_of="2026-05-12",
                symbols=("SPY", "GGAL"),
                fx_pairs=("USDARS_MEP",),
                rate_keys=("k1",),
            )
        )
        self.assertEqual(set(partial.quotes.keys()), {"SPY"})
        self.assertEqual(partial.quotes["SPY"].price, 12345.0)
        self.assertEqual(partial.fx_rates["USDARS_MEP"].rate, 1500.0)
        self.assertEqual(partial.rates["k1"].value, 4.2)

    def test_health_check_is_offline_and_keyless(self) -> None:
        health = StaticExampleSnapshotProvider().health_check()
        self.assertTrue(health["ok"])
        self.assertFalse(health["network_required"])
        self.assertFalse(health["requires_api_key"])


# ---------------------------------------------------------------------------
# Manual-file provider
# ---------------------------------------------------------------------------


class ManualFileSnapshotProviderTests(unittest.TestCase):
    def test_serves_quotes_and_fx_from_existing_file(self) -> None:
        provider = ManualFileSnapshotProvider(EXAMPLE_MARKET)
        request = MarketSnapshotRequest(
            as_of="2026-05-12",
            symbols=("SPY", "GGAL"),
            fx_pairs=("USDARS_MEP",),
            rate_keys=(),
        )
        partial = provider.fetch(request)
        self.assertEqual(set(partial.quotes.keys()), {"SPY", "GGAL"})
        self.assertIn("USDARS_MEP", partial.fx_rates)

    def test_missing_file_returns_empty_partial(self) -> None:
        provider = ManualFileSnapshotProvider("/does/not/exist.json")
        partial = provider.fetch(
            MarketSnapshotRequest(
                as_of="2026-05-12", symbols=("SPY",), fx_pairs=("USDARS_MEP",)
            )
        )
        self.assertEqual(partial.quotes, {})
        self.assertEqual(partial.fx_rates, {})
        self.assertIn("not found", partial.notes)

    def test_invalid_file_returns_empty_partial(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir) / "broken.json"
            tmp.write_text("{not json}", encoding="utf-8")
            provider = ManualFileSnapshotProvider(tmp)
            partial = provider.fetch(
                MarketSnapshotRequest(as_of="2026-05-12", symbols=("SPY",))
            )
            self.assertEqual(partial.quotes, {})

    def test_health_check_reports_path(self) -> None:
        health = ManualFileSnapshotProvider(EXAMPLE_MARKET).health_check()
        self.assertTrue(health["ok"])
        self.assertFalse(health["network_required"])
        self.assertEqual(health["path"], str(EXAMPLE_MARKET))


# ---------------------------------------------------------------------------
# Chain assembler
# ---------------------------------------------------------------------------


class _FakeProvider(MarketSnapshotProvider):
    """Test double; never touches the network."""

    def __init__(
        self,
        name: str,
        *,
        quotes: dict[str, ManualQuote] | None = None,
        fx_rates: dict[str, FxRate] | None = None,
        rates: dict[str, RateInput] | None = None,
        notes: str = "",
    ) -> None:
        self.name = name
        self._quotes = quotes or {}
        self._fx_rates = fx_rates or {}
        self._rates = rates or {}
        self._notes = notes
        self.fetch_calls = 0

    def fetch(self, request: MarketSnapshotRequest) -> PartialMarketSnapshot:
        self.fetch_calls += 1
        return PartialMarketSnapshot(
            provider_name=self.name,
            quotes={
                s: q for s, q in self._quotes.items() if s in request.symbols
            },
            fx_rates={
                p: f for p, f in self._fx_rates.items() if p in request.fx_pairs
            },
            rates={
                k: r for k, r in self._rates.items() if k in request.rate_keys
            },
            notes=self._notes,
        )


def _quote(symbol: str, price: float, provider: str) -> ManualQuote:
    return ManualQuote(
        symbol=symbol,
        asset_class="cedear",
        price=price,
        currency="ARS",
        as_of="2026-05-12",
        provider=provider,
    )


def _fx(pair: str, rate: float, provider: str) -> FxRate:
    return FxRate(
        pair=pair, rate=rate, as_of="2026-05-12", provider=provider
    )


class AssembleMarketSnapshotTests(unittest.TestCase):
    def test_first_hit_wins_per_symbol(self) -> None:
        primary = _FakeProvider(
            "primary",
            quotes={"SPY": _quote("SPY", 10000.0, "primary")},
        )
        secondary = _FakeProvider(
            "secondary",
            quotes={
                "SPY": _quote("SPY", 99999.0, "secondary"),
                "GGAL": _quote("GGAL", 4500.0, "secondary"),
            },
        )
        request = MarketSnapshotRequest(
            as_of="2026-05-12", symbols=("SPY", "GGAL")
        )
        assembled = assemble_market_snapshot(request, [primary, secondary])

        self.assertEqual(assembled.snapshot.quotes["SPY"].price, 10000.0)
        self.assertEqual(
            assembled.provider_sources["quote:SPY"], "primary"
        )
        self.assertEqual(
            assembled.provider_sources["quote:GGAL"], "secondary"
        )

    def test_partial_coverage_yields_partial_completeness(self) -> None:
        primary = _FakeProvider(
            "primary",
            quotes={"SPY": _quote("SPY", 10000.0, "primary")},
            fx_rates={"USDARS_MEP": _fx("USDARS_MEP", 1200.0, "primary")},
        )
        request = MarketSnapshotRequest(
            as_of="2026-05-12",
            symbols=("SPY", "GGAL", "AAPL"),
            fx_pairs=("USDARS_MEP",),
            rate_keys=("money_market_monthly_pct",),
        )
        assembled = assemble_market_snapshot(request, [primary])

        self.assertEqual(assembled.completeness, "partial")
        self.assertEqual(assembled.snapshot.completeness, "partial")
        self.assertEqual(
            set(assembled.missing_symbols), {"GGAL", "AAPL"}
        )
        self.assertEqual(assembled.missing_fx_pairs, ())
        self.assertEqual(
            assembled.missing_rate_keys, ("money_market_monthly_pct",)
        )
        self.assertFalse(assembled.ok)
        warnings = "\n".join(assembled.warnings)
        self.assertIn("GGAL", warnings)
        self.assertIn("money_market_monthly_pct", warnings)
        self.assertIn("manual review only", warnings)

    def test_zero_coverage_yields_minimal(self) -> None:
        primary = _FakeProvider("primary")  # serves nothing
        request = MarketSnapshotRequest(
            as_of="2026-05-12",
            symbols=("SPY",),
            fx_pairs=("USDARS_MEP",),
        )
        assembled = assemble_market_snapshot(request, [primary])
        self.assertEqual(assembled.completeness, "minimal")
        self.assertEqual(set(assembled.missing_symbols), {"SPY"})
        self.assertEqual(assembled.missing_fx_pairs, ("USDARS_MEP",))

    def test_full_coverage_yields_complete(self) -> None:
        primary = _FakeProvider(
            "primary",
            quotes={"SPY": _quote("SPY", 10000.0, "primary")},
            fx_rates={"USDARS_MEP": _fx("USDARS_MEP", 1200.0, "primary")},
        )
        request = MarketSnapshotRequest(
            as_of="2026-05-12",
            symbols=("SPY",),
            fx_pairs=("USDARS_MEP",),
        )
        assembled = assemble_market_snapshot(request, [primary])
        self.assertEqual(assembled.completeness, "complete")
        self.assertEqual(assembled.snapshot.completeness, "complete")
        self.assertTrue(assembled.ok)
        self.assertEqual(assembled.missing_symbols, ())

    def test_manual_review_only_flag_is_set(self) -> None:
        assembled = assemble_market_snapshot(
            MarketSnapshotRequest(as_of="2026-05-12"),
            [StaticExampleSnapshotProvider()],
        )
        self.assertTrue(assembled.snapshot.manual_review_only)
        self.assertFalse(assembled.snapshot.live_trading_enabled)

    def test_chain_with_manual_file_fallback(self) -> None:
        # Primary provider only has SPY; manual file has both SPY and GGAL.
        primary = _FakeProvider(
            "primary",
            quotes={"SPY": _quote("SPY", 10000.0, "primary")},
        )
        manual_file = ManualFileSnapshotProvider(EXAMPLE_MARKET)
        request = MarketSnapshotRequest(
            as_of="2026-05-12",
            symbols=("SPY", "GGAL"),
            fx_pairs=("USDARS_MEP",),
        )
        assembled = assemble_market_snapshot(request, [primary, manual_file])

        self.assertEqual(
            assembled.provider_sources["quote:SPY"], "primary"
        )
        self.assertEqual(
            assembled.provider_sources["quote:GGAL"], "manual_file"
        )
        self.assertIn("USDARS_MEP", assembled.snapshot.fx_rates)
        self.assertEqual(
            assembled.provider_sources["fx:USDARS_MEP"], "manual_file"
        )
        self.assertTrue(assembled.ok)
        self.assertEqual(assembled.completeness, "complete")

    def test_no_providers_yields_empty_minimal(self) -> None:
        assembled = assemble_market_snapshot(
            MarketSnapshotRequest(
                as_of="2026-05-12", symbols=("SPY",)
            ),
            [],
        )
        self.assertEqual(assembled.completeness, "minimal")
        self.assertEqual(assembled.snapshot.quotes, {})
        self.assertEqual(assembled.missing_symbols, ("SPY",))

    def test_assembled_snapshot_passes_input_quality_validators(self) -> None:
        """End-to-end: an assembled snapshot is consumable by the quality
        validators and reports no errors under the default (non-strict) mode
        when fully covered."""
        from src.quality.input_quality import validate_market_snapshot_quality

        assembled = assemble_market_snapshot(
            MarketSnapshotRequest(
                as_of="2026-05-12",
                symbols=("SPY", "GGAL"),
                fx_pairs=("USDARS_MEP",),
            ),
            [StaticExampleSnapshotProvider()],
        )
        self.assertTrue(assembled.ok)

        report = validate_market_snapshot_quality(
            raw_market_data=None,
            market_snapshot=assembled.snapshot,
            expected_date="2026-05-12",
            strict=False,
        )
        self.assertEqual(report.errors_count, 0)

    def test_no_api_keys_in_partial_or_assembled_outputs(self) -> None:
        """Defensive check: no field anywhere should look like an API key."""
        request = MarketSnapshotRequest(
            as_of="2026-05-12",
            symbols=("SPY", "GGAL"),
            fx_pairs=("USDARS_MEP",),
            rate_keys=("money_market_monthly_pct",),
        )
        assembled = assemble_market_snapshot(
            request,
            [StaticExampleSnapshotProvider(), ManualFileSnapshotProvider(EXAMPLE_MARKET)],
        )
        haystack = json.dumps(
            {
                "warnings": list(assembled.warnings),
                "sources": dict(assembled.provider_sources),
                "quotes": {
                    s: {
                        "price": q.price,
                        "currency": q.currency,
                        "provider": q.provider,
                        "notes": q.notes,
                    }
                    for s, q in assembled.snapshot.quotes.items()
                },
                "fx": {
                    p: {
                        "rate": f.rate,
                        "provider": f.provider,
                        "notes": f.notes,
                    }
                    for p, f in assembled.snapshot.fx_rates.items()
                },
            }
        ).lower()
        for forbidden in ("api_key", "apikey", "secret", "token"):
            self.assertNotIn(forbidden, haystack)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
