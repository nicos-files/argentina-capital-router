"""Deterministic monthly-contribution allocator.

This is not a real optimizer. It produces a transparent allocation that respects
target allocations, prefers SPY for core global equity, and splits remaining
capital across selected CEDEARs and Argentina equities. Manual review only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional

from src.market_data.ar_symbols import ArgentinaAsset
from .long_term_policy import LongTermPolicy
from .portfolio_valuation import PortfolioValuation


_BUCKET_TARGET_KEYS: tuple[tuple[str, str], ...] = (
    ("core_global_equity", "core_global_equity_pct"),
    ("cedears_single_names", "cedears_single_names_pct"),
    ("argentina_equity", "argentina_equity_pct"),
    ("cash_or_short_term_yield", "cash_or_short_term_yield_pct"),
)
_CASH_PSEUDO_SYMBOL = "CASH_OR_YIELD"


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


def _bucket_target_pcts(policy: LongTermPolicy) -> dict[str, float]:
    targets = policy.target_allocations
    return {
        bucket: float(targets.get(key, 0.0))
        for bucket, key in _BUCKET_TARGET_KEYS
    }


def _allocate_to_bucket(
    bucket: str,
    amount_usd: float,
    universe: list[ArgentinaAsset],
    rationale_prefix: str,
) -> list[ContributionAllocation]:
    """Spread ``amount_usd`` across the assets associated with ``bucket``.

    Falls back to a deterministic split that mirrors the legacy allocator
    so callers without a portfolio see consistent behavior.
    """
    if amount_usd <= 0:
        return []

    spy_assets = [a for a in universe if a.symbol == "SPY"]
    other_cedears = [
        a for a in universe if a.asset_class == "cedear" and a.symbol != "SPY"
    ]
    ar_equities = [a for a in universe if a.asset_class == "argentina_equity"]

    if bucket == "core_global_equity":
        if spy_assets:
            return [
                ContributionAllocation(
                    symbol="SPY",
                    asset_class="cedear",
                    allocation_usd=amount_usd,
                    bucket=bucket,
                    rationale=f"{rationale_prefix} SPY CEDEAR preferred as broad global equity proxy.",
                )
            ]
        if other_cedears:
            per_each = amount_usd / len(other_cedears)
            return [
                ContributionAllocation(
                    symbol=a.symbol,
                    asset_class=a.asset_class,
                    allocation_usd=per_each,
                    bucket=bucket,
                    rationale=(
                        f"{rationale_prefix} Equal split across enabled CEDEARs "
                        "(SPY unavailable)."
                    ),
                )
                for a in other_cedears
            ]
        return []

    if bucket == "cedears_single_names":
        if not other_cedears:
            return []
        per_each = amount_usd / len(other_cedears)
        return [
            ContributionAllocation(
                symbol=a.symbol,
                asset_class=a.asset_class,
                allocation_usd=per_each,
                bucket=bucket,
                rationale=f"{rationale_prefix} Equal split across enabled single-name CEDEARs.",
            )
            for a in other_cedears
        ]

    if bucket == "argentina_equity":
        if not ar_equities:
            return []
        per_each = amount_usd / len(ar_equities)
        return [
            ContributionAllocation(
                symbol=a.symbol,
                asset_class=a.asset_class,
                allocation_usd=per_each,
                bucket=bucket,
                rationale=f"{rationale_prefix} Equal split across enabled Argentina equities.",
            )
            for a in ar_equities
        ]

    if bucket == "cash_or_short_term_yield":
        return [
            ContributionAllocation(
                symbol=_CASH_PSEUDO_SYMBOL,
                asset_class="cash",
                allocation_usd=amount_usd,
                bucket=bucket,
                rationale=f"{rationale_prefix} Reserve as cash / short-term yield placeholder.",
            )
        ]

    return []


def _normalize_to_contribution(
    allocations: list[ContributionAllocation], contribution: float
) -> list[ContributionAllocation]:
    total = sum(a.allocation_usd for a in allocations)
    if total <= 0 or abs(total - contribution) <= 1e-9:
        return allocations
    factor = contribution / total
    return [
        ContributionAllocation(
            symbol=a.symbol,
            asset_class=a.asset_class,
            allocation_usd=a.allocation_usd * factor,
            bucket=a.bucket,
            rationale=a.rationale,
        )
        for a in allocations
    ]


def allocate_monthly_contribution_with_portfolio(
    contribution_usd: float,
    assets: Iterable[ArgentinaAsset],
    policy: LongTermPolicy,
    valuation: Optional[PortfolioValuation] = None,
) -> List[ContributionAllocation]:
    """Allocate the monthly contribution, optionally aware of current weights.

    If ``valuation`` is ``None`` (or has no usable bucket weights), this falls
    back to :func:`allocate_monthly_contribution` so callers without a portfolio
    snapshot keep the existing deterministic behavior.

    When ``valuation`` is provided, allocate the contribution toward
    *underweight* buckets first (those below their policy target), avoiding
    overweight buckets when possible. The result is normalized to total exactly
    ``contribution_usd`` and remains deterministic for identical inputs.
    """
    contribution = float(contribution_usd)
    if contribution <= 0:
        return []

    if valuation is None or not valuation.bucket_weights or valuation.total_value_usd <= 0:
        return allocate_monthly_contribution(contribution, assets, policy)

    universe = _eligible(assets)
    if not universe:
        return []

    targets = _bucket_target_pcts(policy)
    current = {bucket: float(valuation.bucket_weights.get(bucket, 0.0)) for bucket in targets}
    # Deltas: positive => underweight (target > current). Negative => overweight.
    deltas = {bucket: targets[bucket] - current[bucket] for bucket in targets}

    underweight = {b: d for b, d in deltas.items() if d > 0 and targets[b] > 0}

    if not underweight:
        # All targeted buckets at-or-above target. Pick the single bucket with
        # the smallest excess (closest to target from above) to keep behavior
        # deterministic and avoid feeding overweight areas more aggressively.
        eligible = [b for b, t in targets.items() if t > 0]
        if not eligible:
            return allocate_monthly_contribution(contribution, assets, policy)
        # smallest excess == largest delta (least negative)
        chosen = max(eligible, key=lambda b: deltas[b])
        rationale_prefix = (
            f"All target buckets at/above policy; routing to least-overweight "
            f"bucket {chosen} (delta={deltas[chosen]:.2f} pct)."
        )
        allocations = _allocate_to_bucket(chosen, contribution, universe, rationale_prefix)
        return _normalize_to_contribution(allocations, contribution)

    total_delta = sum(underweight.values())
    allocations: list[ContributionAllocation] = []
    for bucket, delta in underweight.items():
        share = (delta / total_delta) * contribution
        rationale_prefix = (
            f"Bucket {bucket} underweight by {delta:.2f} pct "
            f"(current={current[bucket]:.2f}, target={targets[bucket]:.2f});"
        )
        allocations.extend(
            _allocate_to_bucket(bucket, share, universe, rationale_prefix)
        )

    if not allocations:
        # No eligible assets for the underweight buckets (e.g. universe empty
        # for the relevant asset class). Fall back to deterministic split.
        return allocate_monthly_contribution(contribution, assets, policy)

    return _normalize_to_contribution(allocations, contribution)


__all__ = [
    "ContributionAllocation",
    "allocate_monthly_contribution",
    "allocate_monthly_contribution_with_portfolio",
]
