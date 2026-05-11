from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_UNIVERSE_PATH = ROOT / "data" / "meta" / "asset_universe.csv"


@dataclass(frozen=True)
class AssetDefinition:
    asset_id: str
    enabled: bool
    asset_class: str
    market: str
    currency: str
    lot_size: int
    allow_fractional: bool
    yfinance_symbol: str | None = None
    description: str | None = None


def _clean(value: str | None) -> str:
    return str(value or "").strip()


def _parse_bool(value: str | None, default: bool = False) -> bool:
    normalized = _clean(value).lower()
    if not normalized:
        return default
    return normalized in {"1", "true", "yes", "y", "si", "s"}


def _parse_int(value: str | None, default: int = 1) -> int:
    normalized = _clean(value)
    if not normalized:
        return default
    try:
        return int(float(normalized))
    except ValueError:
        return default


def _normalize_asset_id(asset_id: str) -> str:
    return _clean(asset_id).upper()


def _load_from_path(path: Path) -> list[AssetDefinition]:
    if not path.exists():
        return []

    assets: list[AssetDefinition] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            asset_id = _normalize_asset_id(row.get("asset_id"))
            if not asset_id:
                continue
            assets.append(
                AssetDefinition(
                    asset_id=asset_id,
                    enabled=_parse_bool(row.get("enabled"), default=True),
                    asset_class=_clean(row.get("asset_class")).upper() or "EQUITY",
                    market=_clean(row.get("market")).upper() or "UNKNOWN",
                    currency=_clean(row.get("currency")).upper() or "USD",
                    lot_size=_parse_int(row.get("lot_size"), default=1),
                    allow_fractional=_parse_bool(row.get("allow_fractional"), default=False),
                    yfinance_symbol=_clean(row.get("yfinance_symbol")) or None,
                    description=_clean(row.get("description")) or None,
                )
            )
    return assets


@lru_cache(maxsize=1)
def _load_default_universe() -> tuple[AssetDefinition, ...]:
    return tuple(_load_from_path(DEFAULT_UNIVERSE_PATH))


def load_asset_universe(path: str | Path | None = None) -> list[AssetDefinition]:
    if path is None:
        return list(_load_default_universe())
    return _load_from_path(Path(path))


def get_asset_definition(asset_id: str, path: str | Path | None = None) -> AssetDefinition | None:
    normalized = _normalize_asset_id(asset_id)
    for asset in load_asset_universe(path):
        if asset.asset_id == normalized:
            return asset
    return None


def iter_assets(
    path: str | Path | None = None,
    enabled_only: bool = True,
    asset_classes: Sequence[str] | None = None,
    markets: Sequence[str] | None = None,
    asset_ids: Sequence[str] | None = None,
) -> list[AssetDefinition]:
    assets = load_asset_universe(path)

    class_filter = {str(item).strip().upper() for item in (asset_classes or []) if str(item).strip()}
    market_filter = {str(item).strip().upper() for item in (markets or []) if str(item).strip()}
    asset_filter = {_normalize_asset_id(item) for item in (asset_ids or []) if _clean(item)}

    selected: list[AssetDefinition] = []
    for asset in assets:
        if enabled_only and not asset.enabled:
            continue
        if class_filter and asset.asset_class not in class_filter:
            continue
        if market_filter and asset.market not in market_filter:
            continue
        if asset_filter and asset.asset_id not in asset_filter:
            continue
        selected.append(asset)
    return selected


def asset_ids(assets: Iterable[AssetDefinition]) -> list[str]:
    return [asset.asset_id for asset in assets]
