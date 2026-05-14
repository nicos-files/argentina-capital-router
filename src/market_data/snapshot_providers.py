"""Market-snapshot provider abstraction + assembler (no-cost, no-HTTP).

This module exposes a generic ``MarketSnapshotProvider`` abstraction that
producers can implement to contribute pieces of a ``ManualMarketSnapshot``.
A first-hit-wins chain assembler then merges per-provider partial results
into a single ``ManualMarketSnapshot`` along with a coverage report.

Hard constraints honoured here (mirroring the product-wide policy):
  - Manual review only. No live trading. No broker automation.
  - No network calls. No API keys. No paid data sources.
  - Providers that need keys MUST read them from environment variables or
    explicit CLI arguments only, and MUST degrade gracefully when a key is
    missing (warn + return an empty ``PartialMarketSnapshot``).

This slice ships:
  * the abstraction (``MarketSnapshotProvider``)
  * a deterministic ``StaticExampleSnapshotProvider`` for demos and tests
  * a ``ManualFileSnapshotProvider`` that wraps an existing snapshot JSON
  * ``assemble_market_snapshot`` to walk a provider chain
No real-data HTTP providers are implemented yet; those will be added in a
later slice once their free-tier terms are confirmed.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

from .ar_symbols import normalize_ar_symbol
from .manual_snapshot import (
    FxRate,
    ManualMarketSnapshot,
    ManualQuote,
    RateInput,
    load_manual_market_snapshot,
    normalize_fx_pair,
)


# ---------------------------------------------------------------------------
# Request / response dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MarketSnapshotRequest:
    """What the caller needs covered."""

    as_of: str
    symbols: tuple[str, ...] = ()
    fx_pairs: tuple[str, ...] = ()
    rate_keys: tuple[str, ...] = ()
    base_currency: str = "USD"

    def __post_init__(self) -> None:  # pragma: no cover - simple guard
        if not isinstance(self.as_of, str) or not self.as_of:
            raise ValueError("MarketSnapshotRequest.as_of must be a non-empty string")
        object.__setattr__(
            self,
            "symbols",
            tuple(dict.fromkeys(normalize_ar_symbol(s) for s in self.symbols)),
        )
        object.__setattr__(
            self,
            "fx_pairs",
            tuple(dict.fromkeys(normalize_fx_pair(p) for p in self.fx_pairs)),
        )
        object.__setattr__(self, "rate_keys", tuple(dict.fromkeys(self.rate_keys)))


@dataclass(frozen=True)
class PartialMarketSnapshot:
    """Best-effort subset returned by a single provider."""

    provider_name: str
    quotes: Mapping[str, ManualQuote] = field(default_factory=dict)
    fx_rates: Mapping[str, FxRate] = field(default_factory=dict)
    rates: Mapping[str, RateInput] = field(default_factory=dict)
    notes: str = ""


@dataclass(frozen=True)
class AssembledMarketSnapshot:
    """Result of ``assemble_market_snapshot``."""

    snapshot: ManualMarketSnapshot
    provider_sources: Mapping[str, str]
    missing_symbols: tuple[str, ...]
    missing_fx_pairs: tuple[str, ...]
    missing_rate_keys: tuple[str, ...]
    completeness: str
    warnings: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return (
            not self.missing_symbols
            and not self.missing_fx_pairs
            and not self.missing_rate_keys
        )


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class MarketSnapshotProvider(ABC):
    """Abstract provider contributing pieces of a market snapshot.

    Concrete providers MUST:
      * be safe to instantiate with no network access
      * never raise on a missing item; return an empty ``PartialMarketSnapshot``
      * never log, store, or include API keys in any field
    """

    name: str = "abstract"

    @abstractmethod
    def fetch(self, request: MarketSnapshotRequest) -> PartialMarketSnapshot:
        """Return whatever subset of ``request`` this provider can serve."""

    def health_check(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "ok": True,
            "network_required": False,
            "requires_api_key": False,
        }


# ---------------------------------------------------------------------------
# Static example provider (deterministic, offline)
# ---------------------------------------------------------------------------


def _default_example_quotes(as_of: str) -> dict[str, ManualQuote]:
    """Return a deterministic example set of CEDEAR/AR-equity quotes.

    These are illustrative round numbers used solely for demos and tests.
    They MUST NOT be treated as real market data.
    """
    base = {
        "SPY": (10_500.0, "ARS", "cedear"),
        "AAPL": (9_800.0, "ARS", "cedear"),
        "MELI": (38_500.0, "ARS", "cedear"),
        "KO": (3_750.0, "ARS", "cedear"),
        "GGAL": (4_500.0, "ARS", "argentina_equity"),
        "YPFD": (12_300.0, "ARS", "argentina_equity"),
        "PAMP": (5_120.0, "ARS", "argentina_equity"),
        "ALUA": (1_980.0, "ARS", "argentina_equity"),
        "TXAR": (1_640.0, "ARS", "argentina_equity"),
        "COME": (260.0, "ARS", "argentina_equity"),
    }
    return {
        normalize_ar_symbol(sym): ManualQuote(
            symbol=normalize_ar_symbol(sym),
            asset_class=cls,
            price=price,
            currency=currency,
            as_of=as_of,
            provider="static_example",
            delayed=True,
            notes="static example data; not real market data",
        )
        for sym, (price, currency, cls) in base.items()
    }


def _default_example_fx_rates(as_of: str) -> dict[str, FxRate]:
    return {
        "USDARS_MEP": FxRate(
            pair="USDARS_MEP",
            rate=1_200.0,
            as_of=as_of,
            provider="static_example",
            delayed=True,
            notes="static example FX; not real market data",
        ),
        "USDARS_CCL": FxRate(
            pair="USDARS_CCL",
            rate=1_220.0,
            as_of=as_of,
            provider="static_example",
            delayed=True,
            notes="static example FX; not real market data",
        ),
        "USDARS_OFFICIAL": FxRate(
            pair="USDARS_OFFICIAL",
            rate=1_000.0,
            as_of=as_of,
            provider="static_example",
            delayed=True,
            notes="static example FX; not real market data",
        ),
    }


def _default_example_rates(as_of: str) -> dict[str, RateInput]:
    return {
        "money_market_monthly_pct": RateInput(
            key="money_market_monthly_pct",
            value=2.5,
            as_of=as_of,
            provider="static_example",
            notes="static example rate; not real market data",
        ),
        "caucion_monthly_pct": RateInput(
            key="caucion_monthly_pct",
            value=2.8,
            as_of=as_of,
            provider="static_example",
            notes="static example rate; not real market data",
        ),
        "expected_fx_devaluation_monthly_pct": RateInput(
            key="expected_fx_devaluation_monthly_pct",
            value=1.5,
            as_of=as_of,
            provider="static_example",
            notes="static example rate; not real market data",
        ),
    }


class StaticExampleSnapshotProvider(MarketSnapshotProvider):
    """Deterministic in-memory provider used for demos and tests.

    Loads a default fixture covering the configured Argentina/CEDEAR universe
    plus USDARS rates. No network. No API keys. Manual-review-only.
    """

    name = "static_example"

    def __init__(
        self,
        *,
        quotes: Optional[Mapping[str, ManualQuote]] = None,
        fx_rates: Optional[Mapping[str, FxRate]] = None,
        rates: Optional[Mapping[str, RateInput]] = None,
        provider_name: str = "static_example",
    ) -> None:
        self.name = str(provider_name)
        self._quotes: Optional[dict[str, ManualQuote]] = (
            {normalize_ar_symbol(k): v for k, v in quotes.items()}
            if quotes is not None
            else None
        )
        self._fx_rates: Optional[dict[str, FxRate]] = (
            {normalize_fx_pair(k): v for k, v in fx_rates.items()}
            if fx_rates is not None
            else None
        )
        self._rates: Optional[dict[str, RateInput]] = (
            {str(k): v for k, v in rates.items()} if rates is not None else None
        )

    def fetch(self, request: MarketSnapshotRequest) -> PartialMarketSnapshot:
        quotes_pool = (
            self._quotes
            if self._quotes is not None
            else _default_example_quotes(request.as_of)
        )
        fx_pool = (
            self._fx_rates
            if self._fx_rates is not None
            else _default_example_fx_rates(request.as_of)
        )
        rate_pool = (
            self._rates
            if self._rates is not None
            else _default_example_rates(request.as_of)
        )

        served_quotes = {
            sym: quotes_pool[sym] for sym in request.symbols if sym in quotes_pool
        }
        served_fx = {
            pair: fx_pool[pair] for pair in request.fx_pairs if pair in fx_pool
        }
        served_rates = {
            key: rate_pool[key] for key in request.rate_keys if key in rate_pool
        }

        return PartialMarketSnapshot(
            provider_name=self.name,
            quotes=served_quotes,
            fx_rates=served_fx,
            rates=served_rates,
            notes="deterministic example data; not real market data",
        )

    def health_check(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "ok": True,
            "network_required": False,
            "requires_api_key": False,
            "deterministic": True,
        }


# ---------------------------------------------------------------------------
# Manual-file provider
# ---------------------------------------------------------------------------


class ManualFileSnapshotProvider(MarketSnapshotProvider):
    """Wraps an existing on-disk ``manual_market_snapshot.json`` file.

    Use this at the *tail* of a provider chain so that any gaps in upstream
    free/no-cost providers fall back to a hand-edited snapshot. No network.
    """

    name = "manual_file"

    def __init__(
        self,
        path: Path | str,
        *,
        provider_name: str = "manual_file",
    ) -> None:
        self._path = Path(path)
        self.name = str(provider_name)
        self._cached: Optional[ManualMarketSnapshot] = None

    def _load(self) -> Optional[ManualMarketSnapshot]:
        if self._cached is not None:
            return self._cached
        try:
            self._cached = load_manual_market_snapshot(self._path)
        except (FileNotFoundError, ValueError):
            return None
        return self._cached

    def fetch(self, request: MarketSnapshotRequest) -> PartialMarketSnapshot:
        snapshot = self._load()
        if snapshot is None:
            return PartialMarketSnapshot(
                provider_name=self.name,
                notes=f"manual snapshot file not found or invalid: {self._path}",
            )

        served_quotes = {
            sym: snapshot.quotes[sym]
            for sym in request.symbols
            if sym in snapshot.quotes
        }
        served_fx = {
            pair: snapshot.fx_rates[pair]
            for pair in request.fx_pairs
            if pair in snapshot.fx_rates
        }
        served_rates = {
            key: snapshot.rates[key]
            for key in request.rate_keys
            if key in snapshot.rates
        }
        return PartialMarketSnapshot(
            provider_name=self.name,
            quotes=served_quotes,
            fx_rates=served_fx,
            rates=served_rates,
            notes=f"served from manual file: {self._path}",
        )

    def health_check(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "ok": self._path.exists(),
            "network_required": False,
            "requires_api_key": False,
            "path": str(self._path),
        }


# ---------------------------------------------------------------------------
# Chain assembler
# ---------------------------------------------------------------------------


def _completeness_label(
    requested: int,
    served: int,
    *,
    minimum_for_partial: int = 1,
) -> str:
    if requested == 0:
        return "complete"
    if served == 0:
        return "minimal"
    if served < requested:
        return "partial" if served >= minimum_for_partial else "minimal"
    return "complete"


def assemble_market_snapshot(
    request: MarketSnapshotRequest,
    providers: Sequence[MarketSnapshotProvider],
    *,
    snapshot_id: Optional[str] = None,
    source: str = "provider_chain",
    data_frequency: str = "1d",
) -> AssembledMarketSnapshot:
    """Walk providers in order; first-hit-wins per symbol / FX pair / rate key.

    Always returns an ``AssembledMarketSnapshot``. Missing items become
    quality warnings; the caller decides whether to fail (e.g. via the
    ``input_quality`` strict mode).
    """
    quotes: dict[str, ManualQuote] = {}
    fx_rates: dict[str, FxRate] = {}
    rates: dict[str, RateInput] = {}
    provider_sources: dict[str, str] = {}
    warnings: list[str] = []

    for provider in providers:
        partial = provider.fetch(request)
        for sym, quote in partial.quotes.items():
            if sym in quotes:
                continue
            if sym not in request.symbols:
                continue
            quotes[sym] = quote
            provider_sources[f"quote:{sym}"] = partial.provider_name
        for pair, fx in partial.fx_rates.items():
            if pair in fx_rates:
                continue
            if pair not in request.fx_pairs:
                continue
            fx_rates[pair] = fx
            provider_sources[f"fx:{pair}"] = partial.provider_name
        for key, rate in partial.rates.items():
            if key in rates:
                continue
            if key not in request.rate_keys:
                continue
            rates[key] = rate
            provider_sources[f"rate:{key}"] = partial.provider_name
        if partial.notes:
            warnings.append(f"[{partial.provider_name}] {partial.notes}")

    missing_symbols = tuple(s for s in request.symbols if s not in quotes)
    missing_fx_pairs = tuple(p for p in request.fx_pairs if p not in fx_rates)
    missing_rate_keys = tuple(k for k in request.rate_keys if k not in rates)

    if missing_symbols:
        warnings.append(
            f"missing quotes for symbols: {', '.join(missing_symbols)}"
        )
    if missing_fx_pairs:
        warnings.append(
            f"missing FX rates for pairs: {', '.join(missing_fx_pairs)}"
        )
    if missing_rate_keys:
        warnings.append(
            f"missing rate inputs: {', '.join(missing_rate_keys)}"
        )
    warnings.append("manual review only; no live trading; no broker automation")

    total_requested = (
        len(request.symbols) + len(request.fx_pairs) + len(request.rate_keys)
    )
    total_served = len(quotes) + len(fx_rates) + len(rates)
    completeness = _completeness_label(total_requested, total_served)

    final_id = snapshot_id or f"assembled-{request.as_of}"
    snapshot = ManualMarketSnapshot(
        schema_version="1.0",
        snapshot_id=final_id,
        as_of=request.as_of,
        source=source,
        manual_review_only=True,
        live_trading_enabled=False,
        data_frequency=data_frequency,
        quotes=quotes,
        fx_rates=fx_rates,
        rates=rates,
        warnings=tuple(warnings),
        completeness=completeness,
    )
    return AssembledMarketSnapshot(
        snapshot=snapshot,
        provider_sources=provider_sources,
        missing_symbols=missing_symbols,
        missing_fx_pairs=missing_fx_pairs,
        missing_rate_keys=missing_rate_keys,
        completeness=completeness,
        warnings=tuple(warnings),
    )


# Re-export the Yahoo provider so callers can import every provider from a
# single module without importing transport details. Import is deferred to
# the bottom of the module to avoid a circular import (the Yahoo module
# itself imports the abstract base from this module).
from .yahoo_snapshot_provider import YahooArgentinaMarketDataProvider  # noqa: E402


__all__ = [
    "AssembledMarketSnapshot",
    "ManualFileSnapshotProvider",
    "MarketSnapshotProvider",
    "MarketSnapshotRequest",
    "PartialMarketSnapshot",
    "StaticExampleSnapshotProvider",
    "YahooArgentinaMarketDataProvider",
    "assemble_market_snapshot",
]
