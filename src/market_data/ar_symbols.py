"""Argentina/CEDEAR universe loader and symbol helpers.

Manual-review-only product. No live trading, no broker automation.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_UNIVERSE_PATH = _REPO_ROOT / "config" / "market_universe" / "ar_long_term.json"

_VALID_ASSET_CLASSES = {"argentina_equity", "cedear"}
_VALID_CURRENCIES = {"ARS", "USD", "CCL"}
_VALID_MARKETS = {"BYMA", "IOL", "UNKNOWN"}
_VALID_RISK_BUCKETS = {"low", "medium", "high", "speculative"}

_REQUIRED_ASSET_FIELDS = (
    "symbol",
    "display_name",
    "asset_class",
    "currency",
    "market",
    "enabled",
    "strategy_enabled",
    "long_term_enabled",
    "sector",
    "risk_bucket",
    "min_notional",
    "notes",
    "source_symbol_map",
)

_REQUIRED_TOP_LEVEL_FIELDS = (
    "schema_version",
    "universe_id",
    "base_currency",
    "data_frequency",
    "execution_mode",
    "live_trading_enabled",
    "paper_trading_enabled",
    "assets",
)


@dataclass(frozen=True)
class ArgentinaAsset:
    symbol: str
    display_name: str
    asset_class: str
    currency: str
    market: str
    enabled: bool
    strategy_enabled: bool
    long_term_enabled: bool
    sector: str
    risk_bucket: str
    min_notional: float
    notes: str
    source_symbol_map: Mapping[str, Optional[str]] = field(default_factory=dict)


def normalize_ar_symbol(symbol: str) -> str:
    """Conservative normalization for AR equity / CEDEAR symbols.

    Examples:
        " ggal " -> "GGAL"
        "GGAL.BA" -> "GGAL"
        "meli cedear" -> "MELI"
        "AAPL CEDEAR" -> "AAPL"
    """
    if symbol is None:
        raise ValueError("symbol is required")
    if not isinstance(symbol, str):
        raise TypeError("symbol must be a string")

    token = symbol.strip().upper()
    if not token:
        raise ValueError("symbol must not be empty")

    # Strip common suffixes / tags
    if token.endswith(".BA"):
        token = token[:-3]

    # Split off trailing tags like " CEDEAR"
    parts = token.split()
    if parts:
        token = parts[0]

    return token


def _validate_top_level(data: Mapping[str, Any], path: Path) -> None:
    for field_name in _REQUIRED_TOP_LEVEL_FIELDS:
        if field_name not in data:
            raise ValueError(f"{path}: missing top-level field '{field_name}'")

    if data.get("execution_mode") != "manual_review_only":
        raise ValueError(
            f"{path}: execution_mode must be 'manual_review_only', got {data.get('execution_mode')!r}"
        )
    if data.get("live_trading_enabled") is not False:
        raise ValueError(f"{path}: live_trading_enabled must be false")
    if data.get("paper_trading_enabled") is not False:
        raise ValueError(f"{path}: paper_trading_enabled must be false")
    if not isinstance(data.get("assets"), list):
        raise ValueError(f"{path}: assets must be a list")


def _validate_asset_dict(asset: Mapping[str, Any], index: int, path: Path) -> None:
    if not isinstance(asset, Mapping):
        raise ValueError(f"{path}: asset at index {index} must be an object")
    for field_name in _REQUIRED_ASSET_FIELDS:
        if field_name not in asset:
            raise ValueError(
                f"{path}: asset at index {index} missing required field '{field_name}'"
            )
    if asset["asset_class"] not in _VALID_ASSET_CLASSES:
        raise ValueError(
            f"{path}: asset at index {index} has invalid asset_class {asset['asset_class']!r}"
        )
    if asset["currency"] not in _VALID_CURRENCIES:
        raise ValueError(
            f"{path}: asset at index {index} has invalid currency {asset['currency']!r}"
        )
    if asset["market"] not in _VALID_MARKETS:
        raise ValueError(
            f"{path}: asset at index {index} has invalid market {asset['market']!r}"
        )
    if asset["risk_bucket"] not in _VALID_RISK_BUCKETS:
        raise ValueError(
            f"{path}: asset at index {index} has invalid risk_bucket {asset['risk_bucket']!r}"
        )
    if not isinstance(asset["source_symbol_map"], Mapping):
        raise ValueError(
            f"{path}: asset at index {index} source_symbol_map must be an object"
        )


def _read_json(path: Path) -> Mapping[str, Any]:
    if not path.exists():
        raise ValueError(f"universe config not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON: {exc}") from exc


def load_ar_long_term_universe(path: Path | str | None = None) -> list[ArgentinaAsset]:
    """Load and validate the Argentina/CEDEAR long-term universe."""
    config_path = Path(path) if path is not None else _DEFAULT_UNIVERSE_PATH
    data = _read_json(config_path)
    _validate_top_level(data, config_path)

    assets: list[ArgentinaAsset] = []
    seen_symbols: set[str] = set()

    for index, asset_dict in enumerate(data["assets"]):
        _validate_asset_dict(asset_dict, index, config_path)
        symbol = normalize_ar_symbol(str(asset_dict["symbol"]))
        if symbol in seen_symbols:
            raise ValueError(
                f"{config_path}: duplicate normalized symbol {symbol!r}"
            )
        seen_symbols.add(symbol)
        try:
            min_notional = float(asset_dict["min_notional"])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{config_path}: asset {symbol!r} has invalid min_notional"
            ) from exc

        assets.append(
            ArgentinaAsset(
                symbol=symbol,
                display_name=str(asset_dict["display_name"]),
                asset_class=str(asset_dict["asset_class"]),
                currency=str(asset_dict["currency"]),
                market=str(asset_dict["market"]),
                enabled=bool(asset_dict["enabled"]),
                strategy_enabled=bool(asset_dict["strategy_enabled"]),
                long_term_enabled=bool(asset_dict["long_term_enabled"]),
                sector=str(asset_dict["sector"]),
                risk_bucket=str(asset_dict["risk_bucket"]),
                min_notional=min_notional,
                notes=str(asset_dict["notes"]),
                source_symbol_map=dict(asset_dict["source_symbol_map"]),
            )
        )

    return assets


def get_enabled_long_term_assets(path: Path | str | None = None) -> list[ArgentinaAsset]:
    return [
        asset
        for asset in load_ar_long_term_universe(path)
        if asset.enabled and asset.long_term_enabled
    ]


def get_asset_by_symbol(
    symbol: str, path: Path | str | None = None
) -> ArgentinaAsset | None:
    target = normalize_ar_symbol(symbol)
    for asset in load_ar_long_term_universe(path):
        if asset.symbol == target:
            return asset
    return None


def get_provider_symbol(asset: ArgentinaAsset, provider: str) -> str | None:
    if not isinstance(provider, str) or not provider.strip():
        return None
    key = provider.strip().lower()
    mapping = {str(k).lower(): v for k, v in asset.source_symbol_map.items()}
    if key in mapping and mapping[key] is not None:
        value = mapping[key]
        return str(value) if value else None
    if "internal" in mapping and mapping["internal"] is not None:
        return str(mapping["internal"])
    return None


__all__ = [
    "ArgentinaAsset",
    "normalize_ar_symbol",
    "load_ar_long_term_universe",
    "get_enabled_long_term_assets",
    "get_asset_by_symbol",
    "get_provider_symbol",
]
