"""Deterministic monthly-contribution allocator.

This is not a real optimizer. It produces a transparent allocation that respects
target allocations, prefers SPY for core global equity, and splits remaining
capital across selected CEDEARs and Argentina equities. Manual review only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List

from src.market_data.ar_symbols import ArgentinaAsset
from .long_term_policy import LongTermPolicy


@dataclass(frozen=True)
class ContributionAllocation:
    symbol: str
    asset_class: str
    allocation_usd: float
    bucket: str
    rationale: str


def _eligible(assets: Iterable[ArgentinaAsset]) -> list[ArgentinaAsset]:
    return [
        a for a in assets if a.enabled and a.long_term_enabled
    ]


def allocate_monthly_contribution(
    contribution_usd: float,
    assets: Iterable[ArgentinaAsset],
    policy: LongTermPolicy,
) -> List[ContributionAllocation]:
    contribution = float(contribution_usd)
    if contribution <= 0:
        return []

    universe = _eligible(assets)
    if not universe:
        return []

    targets = policy.target_allocations
    core_pct = float(targets.get("core_global_equity_pct", 0.0)) / 100.0
    cedear_pct = float(targets.get("cedears_single_names_pct", 0.0)) / 100.0
    ar_pct = float(targets.get("argentina_equity_pct", 0.0)) / 100.0
    cash_pct = float(targets.get("cash_or_short_term_yield_pct", 0.0)) / 100.0

    core_amount = contribution * core_pct
    cedear_amount = contribution * cedear_pct
    ar_amount = contribution * ar_pct
    cash_amount = contribution * cash_pct

    allocations: list[ContributionAllocation] = []

    spy_assets = [a for a in universe if a.symbol == "SPY"]
    other_cedears = [a for a in universe if a.asset_class == "cedear" and a.symbol != "SPY"]
    ar_equities = [a for a in universe if a.asset_class == "argentina_equity"]

    # Core global equity bucket -> SPY if available, else split across CEDEARs.
    if core_amount > 0:
        if spy_assets:
            allocations.append(
                ContributionAllocation(
                    symbol="SPY",
                    asset_class="cedear",
                    allocation_usd=core_amount,
                    bucket="core_global_equity",
                    rationale="SPY CEDEAR preferred as broad global equity proxy.",
                )
            )
        elif other_cedears:
            per_each = core_amount / len(other_cedears)
            for asset in other_cedears:
                allocations.append(
                    ContributionAllocation(
                        symbol=asset.symbol,
                        asset_class=asset.asset_class,
                        allocation_usd=per_each,
                        bucket="core_global_equity",
                        rationale="Equal split across enabled CEDEARs as core proxy (SPY unavailable).",
                    )
                )

    # Selected CEDEARs bucket -> equal split across other_cedears
    if cedear_amount > 0 and other_cedears:
        per_each = cedear_amount / len(other_cedears)
        for asset in other_cedears:
            allocations.append(
                ContributionAllocation(
                    symbol=asset.symbol,
                    asset_class=asset.asset_class,
                    allocation_usd=per_each,
                    bucket="cedears_single_names",
                    rationale="Equal split across enabled single-name CEDEARs.",
                )
            )

    # Argentina equities bucket -> equal split across ar_equities
    if ar_amount > 0 and ar_equities:
        per_each = ar_amount / len(ar_equities)
        for asset in ar_equities:
            allocations.append(
                ContributionAllocation(
                    symbol=asset.symbol,
                    asset_class=asset.asset_class,
                    allocation_usd=per_each,
                    bucket="argentina_equity",
                    rationale="Equal split across enabled Argentina equities.",
                )
            )

    # Cash / short-term yield bucket
    if cash_amount > 0:
        allocations.append(
            ContributionAllocation(
                symbol="CASH",
                asset_class="cash",
                allocation_usd=cash_amount,
                bucket="cash_or_short_term_yield",
                rationale="Reserve as cash / short-term yield placeholder.",
            )
        )

    # Normalize so total equals contribution (corrects rounding drift).
    total = sum(a.allocation_usd for a in allocations)
    if total > 0 and abs(total - contribution) > 1e-9:
        factor = contribution / total
        allocations = [
            ContributionAllocation(
                symbol=a.symbol,
                asset_class=a.asset_class,
                allocation_usd=a.allocation_usd * factor,
                bucket=a.bucket,
                rationale=a.rationale,
            )
            for a in allocations
        ]

    return allocations


__all__ = ["ContributionAllocation", "allocate_monthly_contribution"]
