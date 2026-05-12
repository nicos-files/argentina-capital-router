"""Read-only / static market data providers for Argentina equities and CEDEARs.

Manual-review-only product. No live trading. No broker automation. No API keys.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional, Union

from .ar_symbols import ArgentinaAsset, normalize_ar_symbol


SymbolOrAsset = Union[str, ArgentinaAsset]


@dataclass(frozen=True)
class ArgentinaQuote:
    symbol: str
    last_price: float
    currency: str
    as_of: str
    source: str
    is_delayed: bool = True


@dataclass(frozen=True)
class ArgentinaBar:
    symbol: str
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


def _resolve_symbol(asset_or_symbol: SymbolOrAsset) -> str:
    if isinstance(asset_or_symbol, ArgentinaAsset):
        return asset_or_symbol.symbol
    return normalize_ar_symbol(str(asset_or_symbol))


class ArgentinaMarketDataProvider:
    """Base class for Argentina market data providers."""

    name: str = "argentina_base"

    def supports(self, asset: ArgentinaAsset) -> bool:  # pragma: no cover - abstract
        raise NotImplementedError

    def get_latest_quote(self, asset_or_symbol: SymbolOrAsset) -> ArgentinaQuote:  # pragma: no cover - abstract
        raise NotImplementedError

    def get_historical_bars(
        self,
        asset_or_symbol: SymbolOrAsset,
        timeframe: str = "1d",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> list[ArgentinaBar]:  # pragma: no cover - abstract
        raise NotImplementedError

    def health_check(self) -> dict[str, Any]:  # pragma: no cover - abstract
        raise NotImplementedError


class StaticArgentinaMarketDataProvider(ArgentinaMarketDataProvider):
    """In-memory, read-only provider used for tests and offline planning.

    No network. No API keys. No live trading.
    """

    def __init__(
        self,
        quotes: Optional[Mapping[str, ArgentinaQuote]] = None,
        bars: Optional[Mapping[str, Iterable[ArgentinaBar]]] = None,
        provider_name: str = "static_ar",
    ) -> None:
        self.name = str(provider_name)
        self._quotes: dict[str, ArgentinaQuote] = {}
        if quotes:
            for symbol, quote in quotes.items():
                self._quotes[normalize_ar_symbol(symbol)] = quote
        self._bars: dict[str, list[ArgentinaBar]] = {}
        if bars:
            for symbol, items in bars.items():
                self._bars[normalize_ar_symbol(symbol)] = list(items)

    def supports(self, asset: ArgentinaAsset) -> bool:
        if not isinstance(asset, ArgentinaAsset):
            return False
        if not asset.enabled:
            return False
        return asset.asset_class in ("argentina_equity", "cedear")

    def get_latest_quote(self, asset_or_symbol: SymbolOrAsset) -> ArgentinaQuote:
        symbol = _resolve_symbol(asset_or_symbol)
        if symbol not in self._quotes:
            raise KeyError(f"no quote loaded for symbol {symbol!r}")
        return self._quotes[symbol]

    def get_historical_bars(
        self,
        asset_or_symbol: SymbolOrAsset,
        timeframe: str = "1d",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> list[ArgentinaBar]:
        if timeframe != "1d":
            raise ValueError(
                f"unsupported timeframe {timeframe!r}; only '1d' is supported"
            )
        symbol = _resolve_symbol(asset_or_symbol)
        bars = list(self._bars.get(symbol, []))

        def _in_range(bar: ArgentinaBar) -> bool:
            if start_date is not None and bar.date < start_date:
                return False
            if end_date is not None and bar.date > end_date:
                return False
            return True

        return [bar for bar in bars if _in_range(bar)]

    def health_check(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "ok": True,
            "read_only": True,
            "network_required": False,
            "live_trading_enabled": False,
            "quotes_loaded": len(self._quotes),
            "bars_loaded": sum(len(v) for v in self._bars.values()),
        }


class IOLPublicDelayedProvider(ArgentinaMarketDataProvider):
    """Placeholder for a future delayed public provider (e.g. IOL public).

    NOT suitable for serious intraday trading. Not implemented in this slice.
    This is intentionally read-only and offline today.
    """

    name = "iol_public_delayed"

    def supports(self, asset: ArgentinaAsset) -> bool:  # pragma: no cover - placeholder
        raise NotImplementedError("IOLPublicDelayedProvider not implemented yet")

    def get_latest_quote(self, asset_or_symbol: SymbolOrAsset) -> ArgentinaQuote:  # pragma: no cover - placeholder
        raise NotImplementedError("IOLPublicDelayedProvider not implemented yet")

    def get_historical_bars(
        self,
        asset_or_symbol: SymbolOrAsset,
        timeframe: str = "1d",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> list[ArgentinaBar]:  # pragma: no cover - placeholder
        raise NotImplementedError("IOLPublicDelayedProvider not implemented yet")

    def health_check(self) -> dict[str, Any]:  # pragma: no cover - placeholder
        raise NotImplementedError("IOLPublicDelayedProvider not implemented yet")


__all__ = [
    "ArgentinaQuote",
    "ArgentinaBar",
    "ArgentinaMarketDataProvider",
    "StaticArgentinaMarketDataProvider",
    "IOLPublicDelayedProvider",
]
