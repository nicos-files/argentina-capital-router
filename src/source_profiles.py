from __future__ import annotations

from typing import Iterable

from src.asset_universe import AssetDefinition


FREE_PRICE_MARKETS = {"US", "FX"}
FREE_FUNDAMENTALS_MARKETS = {"US"}
FREE_FUNDAMENTALS_ASSET_CLASSES = {"EQUITY"}

FREE_PROFILE_ASSET_IDS: dict[str, list[str]] = {
    "free-us-small": [
        "AAPL.US",
        "MSFT.US",
        "NVDA.US",
        "AMZN.US",
        "GOOGL.US",
        "META.US",
        "TSLA.US",
        "AMD.US",
    ],
    "free-portfolio": [
        "AAPL.US",
        "MSFT.US",
        "NVDA.US",
        "AMZN.US",
        "GOOGL.US",
        "META.US",
        "JPM.US",
        "SPY.US",
        "QQQ.US",
    ],
    "free-forex": [
        "EURUSD.FX",
        "GBPUSD.FX",
        "AUDUSD.FX",
        "NZDUSD.FX",
    ],
}
FREE_PROFILE_ASSET_IDS["free-core"] = (
    FREE_PROFILE_ASSET_IDS["free-us-small"] + FREE_PROFILE_ASSET_IDS["free-forex"]
)
FREE_PROFILE_ASSET_IDS["free-all-supported"] = (
    FREE_PROFILE_ASSET_IDS["free-portfolio"] + FREE_PROFILE_ASSET_IDS["free-forex"]
)


def get_profile_asset_ids(profile: str | None) -> list[str]:
    if not profile:
        return []
    key = profile.strip().lower()
    if key not in FREE_PROFILE_ASSET_IDS:
        valid = ", ".join(sorted(FREE_PROFILE_ASSET_IDS))
        raise ValueError(f"Unknown profile '{profile}'. Valid profiles: {valid}")
    return list(dict.fromkeys(FREE_PROFILE_ASSET_IDS[key]))


def is_free_price_supported(asset: AssetDefinition) -> bool:
    return asset.market in FREE_PRICE_MARKETS


def is_free_fundamentals_supported(asset: AssetDefinition) -> bool:
    return asset.market in FREE_FUNDAMENTALS_MARKETS and asset.asset_class in FREE_FUNDAMENTALS_ASSET_CLASSES


def filter_free_price_assets(assets: Iterable[AssetDefinition]) -> list[AssetDefinition]:
    return [asset for asset in assets if is_free_price_supported(asset)]


def filter_free_fundamentals_assets(assets: Iterable[AssetDefinition]) -> list[AssetDefinition]:
    return [asset for asset in assets if is_free_fundamentals_supported(asset)]
