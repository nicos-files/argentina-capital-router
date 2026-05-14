"""Best-effort, free, no-auth Yahoo Finance snapshot provider.

Plugs into the existing ``MarketSnapshotProvider`` chain. Designed to:

* be **read-only and delayed** - never used for live trading or order routing,
* require **no API key** and no payment,
* use only the **public, no-auth** quote endpoint,
* fail **gracefully** on network / parse / per-symbol errors,
* expose an **injectable transport** so tests never touch the network,
* never log, store, or echo any secret (there are no secrets here).

Coverage is intentionally best-effort. Yahoo may not list every Argentina /
CEDEAR symbol, and even when it does, the prices are delayed. Missing
symbols produce warnings and a ``partial`` snapshot; the rest of the
pipeline (``input_quality``, ``--strict``) already understands that.

Manual review only. No live trading. No broker automation. No orders.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from .ar_symbols import (
    ArgentinaAsset,
    get_enabled_long_term_assets,
    load_ar_long_term_universe,
    normalize_ar_symbol,
)
from .manual_snapshot import FxRate, ManualQuote, RateInput
from .snapshot_providers import (
    MarketSnapshotProvider,
    MarketSnapshotRequest,
    PartialMarketSnapshot,
)


_YAHOO_QUOTE_URL = "https://query1.finance.yahoo.com/v7/finance/quote"
_PROVIDER_SOURCE_KEY = "yfinance"
_DEFAULT_TIMEOUT_SECONDS = 5.0

# Transport contract: given a URL, return a parsed JSON ``dict`` or raise.
# The provider itself catches any exception and degrades to an empty result.
Transport = Callable[[str, float], Mapping[str, Any]]


def _default_urllib_transport(url: str, timeout: float) -> Mapping[str, Any]:
    """Production transport. Stdlib-only, no third-party deps."""
    # Imported lazily so unit tests that mock the transport never trigger
    # any import-side network setup or DNS lookups.
    from urllib.request import Request, urlopen

    request = Request(
        url,
        headers={
            # Yahoo's public quote endpoint sometimes returns 4xx without
            # a User-Agent. This UA does not identify or authenticate the
            # caller in any way - it is a generic browser string.
            "User-Agent": (
                "Mozilla/5.0 (compatible; argentina-capital-router/0.1; "
                "manual-review-only)"
            ),
            "Accept": "application/json",
        },
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - public endpoint
        raw = response.read()
    return json.loads(raw)


def _coerce_iter_assets(
    assets: Optional[Iterable[ArgentinaAsset]],
    universe_path: Optional[str] = None,
) -> list[ArgentinaAsset]:
    if assets is not None:
        return list(assets)
    # Default to the configured enabled long-term universe. ``ValueError``
    # at load time is allowed to propagate because it indicates a broken
    # config file, not a transient runtime error.
    try:
        return get_enabled_long_term_assets(universe_path)
    except ValueError:
        # If even the universe is unavailable, fall back to the full
        # universe loader; if that also fails, return an empty list and
        # let the caller log a warning. We do not raise at construction
        # time; the contract says missing data must degrade gracefully.
        try:
            return load_ar_long_term_universe(universe_path)
        except ValueError:
            return []


class YahooArgentinaMarketDataProvider(MarketSnapshotProvider):
    """Free / no-auth Yahoo Finance snapshot provider.

    Read-only, delayed, best-effort. Coverage for Argentina equities and
    CEDEARs may be incomplete. The provider:

      * resolves each requested internal symbol to its Yahoo symbol via
        the universe's ``source_symbol_map["yfinance"]`` mapping,
      * batches them into a single quote request,
      * returns a ``PartialMarketSnapshot`` containing only symbols Yahoo
        actually answered for,
      * never raises on network, JSON, or per-symbol errors - it returns
        an empty partial with a ``notes`` string instead.

    No FX rates or rate inputs are served in this slice; pass those via
    ``--usdars-mep`` / ``--*-pct`` CLI flags or a hand-edited fallback.
    """

    name = "yahoo"

    def __init__(
        self,
        *,
        assets: Optional[Iterable[ArgentinaAsset]] = None,
        transport: Optional[Transport] = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        universe_path: Optional[str] = None,
        provider_name: str = "yahoo",
    ) -> None:
        self.name = str(provider_name)
        self._transport: Transport = transport or _default_urllib_transport
        self._timeout = float(timeout_seconds)
        self._assets = _coerce_iter_assets(assets, universe_path=universe_path)
        self._last_error: Optional[str] = None

    # ------------------------------------------------------------------
    # Symbol resolution
    # ------------------------------------------------------------------

    def _asset_by_internal_symbol(self, symbol: str) -> Optional[ArgentinaAsset]:
        target = normalize_ar_symbol(symbol)
        for asset in self._assets:
            if asset.symbol == target:
                return asset
        return None

    def _resolve(
        self, requested_symbols: Sequence[str]
    ) -> tuple[dict[str, ArgentinaAsset], list[str]]:
        """Return (yahoo_symbol -> asset) and a list of unresolved internals.

        Resolution is strict: we use ``source_symbol_map["yfinance"]`` only
        and do NOT fall back to the internal symbol. Yahoo's ticker space
        is different (e.g. local equities need a ``.BA`` suffix), so a
        missing or null ``yfinance`` mapping must be treated as "we don't
        know how to ask Yahoo about this name" rather than guessing.
        """
        resolved: dict[str, ArgentinaAsset] = {}
        unresolved: list[str] = []
        for symbol in requested_symbols:
            asset = self._asset_by_internal_symbol(symbol)
            if asset is None:
                unresolved.append(symbol)
                continue
            mapping = {
                str(k).lower(): v
                for k, v in (asset.source_symbol_map or {}).items()
            }
            yahoo_symbol = mapping.get(_PROVIDER_SOURCE_KEY)
            if not yahoo_symbol:
                unresolved.append(symbol)
                continue
            resolved[str(yahoo_symbol)] = asset
        return resolved, unresolved

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    def _fetch_quote_payload(
        self, yahoo_symbols: Sequence[str]
    ) -> Optional[Mapping[str, Any]]:
        if not yahoo_symbols:
            return None
        url = (
            f"{_YAHOO_QUOTE_URL}?symbols=" + ",".join(sorted(set(yahoo_symbols)))
        )
        try:
            payload = self._transport(url, self._timeout)
        except Exception as exc:  # pragma: no cover - production fallthrough
            # Production: degrade gracefully. The message is informational
            # only and never contains secrets - this provider has none.
            self._last_error = type(exc).__name__
            return None
        if not isinstance(payload, Mapping):
            self._last_error = "transport_returned_non_mapping"
            return None
        return payload

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_results(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        # Yahoo's v7 quote response: { "quoteResponse": { "result": [...], "error": null } }
        if "quoteResponse" not in payload:
            return []
        block = payload.get("quoteResponse")
        if not isinstance(block, Mapping):
            return []
        result = block.get("result")
        if not isinstance(result, list):
            return []
        return [item for item in result if isinstance(item, Mapping)]

    def _parse_quote(
        self,
        item: Mapping[str, Any],
        asset: ArgentinaAsset,
        as_of: str,
    ) -> Optional[ManualQuote]:
        price_raw = item.get("regularMarketPrice")
        if price_raw is None:
            return None
        try:
            price = float(price_raw)
        except (TypeError, ValueError):
            return None
        if price <= 0:
            return None
        currency = str(item.get("currency") or asset.currency or "ARS").upper()
        return ManualQuote(
            symbol=asset.symbol,
            asset_class=asset.asset_class,
            price=price,
            currency=currency,
            as_of=as_of,
            provider=self.name,
            delayed=True,
            notes=(
                "yahoo: free, no-auth, delayed quote; read-only; "
                "best-effort coverage"
            ),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch(self, request: MarketSnapshotRequest) -> PartialMarketSnapshot:
        self._last_error = None
        # No FX or rate inputs in this slice; explicitly return empty maps.
        fx_rates: dict[str, FxRate] = {}
        rates: dict[str, RateInput] = {}

        if not request.symbols:
            return PartialMarketSnapshot(
                provider_name=self.name,
                quotes={},
                fx_rates=fx_rates,
                rates=rates,
                notes="yahoo: no symbols requested; nothing to do",
            )

        resolved, unresolved = self._resolve(request.symbols)
        notes_parts: list[str] = [
            "yahoo: free, no-auth, delayed quotes; read-only; best-effort"
        ]
        if unresolved:
            notes_parts.append(
                "unmapped (no yfinance entry): " + ", ".join(unresolved)
            )

        if not resolved:
            return PartialMarketSnapshot(
                provider_name=self.name,
                quotes={},
                fx_rates=fx_rates,
                rates=rates,
                notes="; ".join(notes_parts),
            )

        payload = self._fetch_quote_payload(list(resolved.keys()))
        if payload is None:
            err = self._last_error or "no_response"
            notes_parts.append(f"transport failed: {err}; returning no quotes")
            return PartialMarketSnapshot(
                provider_name=self.name,
                quotes={},
                fx_rates=fx_rates,
                rates=rates,
                notes="; ".join(notes_parts),
            )

        quotes: dict[str, ManualQuote] = {}
        items_by_symbol: dict[str, Mapping[str, Any]] = {}
        for item in self._extract_results(payload):
            sym = str(item.get("symbol") or "")
            if sym and sym in resolved:
                items_by_symbol[sym] = item

        for yahoo_sym, asset in resolved.items():
            item = items_by_symbol.get(yahoo_sym)
            if item is None:
                continue
            quote = self._parse_quote(item, asset, request.as_of)
            if quote is None:
                continue
            quotes[asset.symbol] = quote

        served = set(quotes.keys())
        resolved_internals = {asset.symbol for asset in resolved.values()}
        missing_after_resolution = sorted(resolved_internals - served)
        if missing_after_resolution:
            notes_parts.append(
                "yahoo returned no usable price for: "
                + ", ".join(missing_after_resolution)
            )

        return PartialMarketSnapshot(
            provider_name=self.name,
            quotes=quotes,
            fx_rates=fx_rates,
            rates=rates,
            notes="; ".join(notes_parts),
        )

    def health_check(self) -> dict[str, Any]:
        return {
            "provider": self.name,
            "ok": True,
            "network_required": True,
            "requires_api_key": False,
            "read_only": True,
            "delayed": True,
            "coverage": "best_effort",
            "endpoint": _YAHOO_QUOTE_URL,
            "notes": (
                "Free, no-auth public endpoint. Coverage for Argentina / "
                "CEDEAR symbols may be incomplete. Never used for live "
                "trading or order routing."
            ),
            "last_transport_error": self._last_error,
        }


__all__ = [
    "Transport",
    "YahooArgentinaMarketDataProvider",
]
