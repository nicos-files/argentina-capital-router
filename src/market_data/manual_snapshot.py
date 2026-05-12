"""Manual market snapshot loader.

Read-only. No network. No broker. No API keys. Manual review only.

The snapshot is a local JSON file produced by a human (or another offline tool)
that captures latest known prices, FX rates, and macro/rate assumptions. It is
explicitly *delayed* and unsuitable for intraday trading.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from .ar_providers import ArgentinaQuote, StaticArgentinaMarketDataProvider
from .ar_symbols import normalize_ar_symbol


_REQUIRED_TOP_LEVEL_FIELDS = (
    "schema_version",
    "snapshot_id",
    "as_of",
    "source",
    "manual_review_only",
    "live_trading_enabled",
    "data_frequency",
    "quotes",
    "fx_rates",
    "rates",
)

_VALID_COMPLETENESS = {"complete", "partial", "minimal", "unknown"}


@dataclass(frozen=True)
class ManualQuote:
    symbol: str
    asset_class: str
    price: float
    currency: str
    as_of: str
    provider: str = "manual"
    delayed: bool = True
    notes: str = ""


@dataclass(frozen=True)
class FxRate:
    pair: str
    rate: float
    as_of: str
    provider: str = "manual"
    delayed: bool = True
    notes: str = ""


@dataclass(frozen=True)
class RateInput:
    key: str
    value: float
    as_of: str
    provider: str = "manual"
    notes: str = ""


@dataclass(frozen=True)
class ManualMarketSnapshot:
    schema_version: str
    snapshot_id: str
    as_of: str
    source: str
    manual_review_only: bool
    live_trading_enabled: bool
    data_frequency: str
    quotes: Mapping[str, ManualQuote]
    fx_rates: Mapping[str, FxRate]
    rates: Mapping[str, RateInput]
    warnings: tuple = field(default_factory=tuple)
    completeness: str = "unknown"


def normalize_fx_pair(pair: str) -> str:
    """Normalize an FX pair label.

    - trim
    - uppercase
    - replace ``/``, ``-``, and whitespace with ``_``
    - collapse repeated underscores
    - strip leading/trailing underscores

    Examples:
        ``"usdars mep"`` -> ``"USDARS_MEP"``
        ``"USD/ARS CCL"`` -> ``"USD_ARS_CCL"``
        ``" usd-ars  official "`` -> ``"USD_ARS_OFFICIAL"``
    """
    if pair is None:
        raise ValueError("pair is required")
    if not isinstance(pair, str):
        raise TypeError("pair must be a string")

    token = pair.strip().upper()
    if not token:
        raise ValueError("pair must not be empty")

    for ch in ("/", "-"):
        token = token.replace(ch, "_")
    # collapse any whitespace into underscores
    parts = [chunk for chunk in token.split() if chunk]
    token = "_".join(parts) if parts else token
    # collapse double underscores
    while "__" in token:
        token = token.replace("__", "_")
    return token.strip("_")


def _coerce_float(value: Any, *, field_name: str, ctx: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{ctx}: {field_name} must be numeric") from exc


def _validate_top_level(data: Mapping[str, Any], path: Path) -> None:
    if not isinstance(data, Mapping):
        raise ValueError(f"{path}: snapshot must be an object")
    for field_name in _REQUIRED_TOP_LEVEL_FIELDS:
        if field_name not in data:
            raise ValueError(f"{path}: missing top-level field {field_name!r}")
    if data.get("manual_review_only") is not True:
        raise ValueError(f"{path}: manual_review_only must be true")
    if data.get("live_trading_enabled") is not False:
        raise ValueError(f"{path}: live_trading_enabled must be false")
    if not isinstance(data.get("quotes"), list):
        raise ValueError(f"{path}: quotes must be a list")
    if not isinstance(data.get("fx_rates"), Mapping):
        raise ValueError(f"{path}: fx_rates must be an object")
    if not isinstance(data.get("rates"), Mapping):
        raise ValueError(f"{path}: rates must be an object")


def _parse_quotes(
    items: Iterable[Mapping[str, Any]], path: Path
) -> dict[str, ManualQuote]:
    out: dict[str, ManualQuote] = {}
    for index, raw in enumerate(items):
        if not isinstance(raw, Mapping):
            raise ValueError(f"{path}: quote at index {index} must be an object")
        for required in ("symbol", "price", "currency", "as_of"):
            if required not in raw:
                raise ValueError(
                    f"{path}: quote at index {index} missing required field {required!r}"
                )
        symbol = normalize_ar_symbol(str(raw["symbol"]))
        price = _coerce_float(
            raw["price"], field_name="price", ctx=f"{path}: quote {symbol!r}"
        )
        if price <= 0:
            raise ValueError(
                f"{path}: quote {symbol!r} has non-positive price {price}"
            )
        if symbol in out:
            raise ValueError(f"{path}: duplicate quote for symbol {symbol!r}")
        out[symbol] = ManualQuote(
            symbol=symbol,
            asset_class=str(raw.get("asset_class", "")),
            price=price,
            currency=str(raw["currency"]),
            as_of=str(raw["as_of"]),
            provider=str(raw.get("provider", "manual")),
            delayed=bool(raw.get("delayed", True)),
            notes=str(raw.get("notes", "")),
        )
    return out


def _parse_fx_rates(
    items: Mapping[str, Any], path: Path
) -> dict[str, FxRate]:
    out: dict[str, FxRate] = {}
    for raw_key, raw in items.items():
        if not isinstance(raw, Mapping):
            raise ValueError(
                f"{path}: fx_rates[{raw_key!r}] must be an object"
            )
        if "rate" not in raw or "as_of" not in raw:
            raise ValueError(
                f"{path}: fx_rates[{raw_key!r}] missing required fields"
            )
        pair = normalize_fx_pair(str(raw_key))
        rate = _coerce_float(
            raw["rate"], field_name="rate", ctx=f"{path}: fx_rates[{pair!r}]"
        )
        if rate <= 0:
            raise ValueError(
                f"{path}: fx_rates[{pair!r}] has non-positive rate {rate}"
            )
        if pair in out:
            raise ValueError(f"{path}: duplicate fx pair {pair!r}")
        out[pair] = FxRate(
            pair=pair,
            rate=rate,
            as_of=str(raw["as_of"]),
            provider=str(raw.get("provider", "manual")),
            delayed=bool(raw.get("delayed", True)),
            notes=str(raw.get("notes", "")),
        )
    return out


def _parse_rates(items: Mapping[str, Any], path: Path) -> dict[str, RateInput]:
    out: dict[str, RateInput] = {}
    for raw_key, raw in items.items():
        if not isinstance(raw, Mapping):
            raise ValueError(f"{path}: rates[{raw_key!r}] must be an object")
        if "value" not in raw or "as_of" not in raw:
            raise ValueError(
                f"{path}: rates[{raw_key!r}] missing required fields"
            )
        key = str(raw_key).strip()
        if not key:
            raise ValueError(f"{path}: rates contains empty key")
        value = _coerce_float(
            raw["value"], field_name="value", ctx=f"{path}: rates[{key!r}]"
        )
        out[key] = RateInput(
            key=key,
            value=value,
            as_of=str(raw["as_of"]),
            provider=str(raw.get("provider", "manual")),
            notes=str(raw.get("notes", "")),
        )
    return out


def _parse_quality(data: Mapping[str, Any], path: Path) -> tuple[tuple[str, ...], str]:
    quality = data.get("quality")
    if quality is None:
        return tuple(), "unknown"
    if not isinstance(quality, Mapping):
        raise ValueError(f"{path}: quality must be an object if present")
    warnings_raw = quality.get("warnings", [])
    if warnings_raw is None:
        warnings: tuple[str, ...] = tuple()
    elif isinstance(warnings_raw, list):
        warnings = tuple(str(w) for w in warnings_raw)
    else:
        raise ValueError(f"{path}: quality.warnings must be a list when present")
    completeness = str(quality.get("completeness", "unknown")).strip().lower()
    if completeness not in _VALID_COMPLETENESS:
        completeness = "unknown"
    return warnings, completeness


def load_manual_market_snapshot(path: str | Path) -> ManualMarketSnapshot:
    config_path = Path(path)
    if not config_path.exists():
        raise ValueError(f"manual market snapshot not found: {config_path}")
    try:
        with config_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{config_path}: invalid JSON: {exc}") from exc

    _validate_top_level(data, config_path)

    quotes = _parse_quotes(data["quotes"], config_path)
    fx_rates = _parse_fx_rates(data["fx_rates"], config_path)
    rates = _parse_rates(data["rates"], config_path)
    warnings, completeness = _parse_quality(data, config_path)

    return ManualMarketSnapshot(
        schema_version=str(data["schema_version"]),
        snapshot_id=str(data["snapshot_id"]),
        as_of=str(data["as_of"]),
        source=str(data["source"]),
        manual_review_only=True,
        live_trading_enabled=False,
        data_frequency=str(data["data_frequency"]),
        quotes=quotes,
        fx_rates=fx_rates,
        rates=rates,
        warnings=warnings,
        completeness=completeness,
    )


def snapshot_to_static_provider(
    snapshot: ManualMarketSnapshot,
) -> StaticArgentinaMarketDataProvider:
    """Convert snapshot quotes into a read-only static provider."""
    quotes: dict[str, ArgentinaQuote] = {}
    for symbol, q in snapshot.quotes.items():
        quotes[symbol] = ArgentinaQuote(
            symbol=symbol,
            last_price=float(q.price),
            currency=q.currency,
            as_of=q.as_of,
            source="manual_snapshot",
            is_delayed=True,
        )
    return StaticArgentinaMarketDataProvider(
        quotes=quotes,
        bars=None,
        provider_name="manual_snapshot",
    )


def get_fx_rate(
    snapshot: ManualMarketSnapshot, pair: str
) -> Optional[FxRate]:
    normalized = normalize_fx_pair(pair)
    return snapshot.fx_rates.get(normalized)


def get_rate_input(
    snapshot: ManualMarketSnapshot, key: str
) -> Optional[RateInput]:
    if not isinstance(key, str):
        return None
    target = key.strip()
    if not target:
        return None
    if target in snapshot.rates:
        return snapshot.rates[target]
    # case-insensitive fallback
    lower = target.lower()
    for stored_key, entry in snapshot.rates.items():
        if stored_key.lower() == lower:
            return entry
    return None


def summarize_snapshot(snapshot: ManualMarketSnapshot) -> dict[str, Any]:
    return {
        "snapshot_id": snapshot.snapshot_id,
        "as_of": snapshot.as_of,
        "quotes_loaded": len(snapshot.quotes),
        "fx_rates_loaded": len(snapshot.fx_rates),
        "rates_loaded": len(snapshot.rates),
        "warnings": list(snapshot.warnings),
        "completeness": snapshot.completeness,
    }


__all__ = [
    "ManualQuote",
    "FxRate",
    "RateInput",
    "ManualMarketSnapshot",
    "normalize_fx_pair",
    "load_manual_market_snapshot",
    "snapshot_to_static_provider",
    "get_fx_rate",
    "get_rate_input",
    "summarize_snapshot",
]
