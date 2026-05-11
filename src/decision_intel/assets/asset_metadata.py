from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.asset_universe import get_asset_definition


@dataclass(frozen=True)
class AssetMetadata:
    asset_class: str
    market: str
    currency: str
    lot_size: int
    allow_fractional: bool
    price_source: str
    fx_rate_used: Optional[float]
    fx_rate_source: str


def get_asset_metadata(asset_id: str, price_source: str = "features.close") -> AssetMetadata:
    normalized = asset_id.strip().upper()
    asset = get_asset_definition(normalized)

    if asset is not None:
        asset_class = asset.asset_class
        market = asset.market
        currency = asset.currency
        allow_fractional = asset.allow_fractional
        lot_size = asset.lot_size
    elif "." not in normalized:
        asset_class = "EQUITY"
        market = "US"
        currency = "USD"
        allow_fractional = True
        lot_size = 1
    elif normalized.endswith(".US"):
        asset_class = "EQUITY"
        market = "US"
        currency = "USD"
        allow_fractional = True
        lot_size = 1
    elif normalized.endswith(".FX"):
        asset_class = "FOREX"
        market = "FX"
        currency = "USD"
        allow_fractional = True
        lot_size = 1
    else:
        asset_class = "EQUITY"
        market = "BA"
        currency = "ARS"
        allow_fractional = False
        lot_size = 1

    if currency == "USD":
        fx_rate_used = 1.0
        fx_rate_source = "native_usd"
    else:
        fx_rate_used = None
        fx_rate_source = "missing"
    return AssetMetadata(
        asset_class=asset_class,
        market=market,
        currency=currency,
        lot_size=lot_size,
        allow_fractional=allow_fractional,
        price_source=price_source,
        fx_rate_used=fx_rate_used,
        fx_rate_source=fx_rate_source,
    )
