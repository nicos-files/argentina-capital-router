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


@dataclass(frozen=True)
class SkippedContributionAllocation:
    symbol: str
    asset_class: str
    bucket: str
    suggested_usd: float
    reason: str


@dataclass(frozen=True)
class ContributionAllocationPlan:
    allocations: tuple
    skipped_allocations: tuple
    unallocated_usd: float
    warnings: tuple


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


def _policy_min_trade_usd(policy: LongTermPolicy) -> float:
    try:
        return max(0.0, float(policy.constraints.get("min_trade_usd", 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _policy_max_allocations(policy: LongTermPolicy) -> int:
    raw = policy.constraints.get("max_allocations_per_contribution", 0)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return 0
    return max(0, value)


def _bucket_is_overweight(
    bucket: str, valuation: Optional[PortfolioValuation], policy: LongTermPolicy
) -> bool:
    if valuation is None or not valuation.bucket_weights:
        return False
    targets = _bucket_target_pcts(policy)
    target = float(targets.get(bucket, 0.0))
    if target <= 0:
        return False
    current = float(valuation.bucket_weights.get(bucket, 0.0))
    return current > target


def _redistribute(
    kept: list[ContributionAllocation], extra_usd: float
) -> list[ContributionAllocation]:
    """Spread ``extra_usd`` across ``kept`` allocations proportionally."""
    if extra_usd <= 0 or not kept:
        return kept
    base_total = sum(a.allocation_usd for a in kept)
    if base_total <= 0:
        per_each = extra_usd / len(kept)
        return [
            ContributionAllocation(
                symbol=a.symbol,
                asset_class=a.asset_class,
                allocation_usd=a.allocation_usd + per_each,
                bucket=a.bucket,
                rationale=a.rationale,
            )
            for a in kept
        ]
    return [
        ContributionAllocation(
            symbol=a.symbol,
            asset_class=a.asset_class,
            allocation_usd=a.allocation_usd + extra_usd * (a.allocation_usd / base_total),
            bucket=a.bucket,
            rationale=a.rationale,
        )
        for a in kept
    ]


def _normalize_total(
    allocations: list[ContributionAllocation], target_total: float
) -> list[ContributionAllocation]:
    total = sum(a.allocation_usd for a in allocations)
    if total <= 0 or abs(total - target_total) <= 1e-9:
        return allocations
    factor = target_total / total
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


def build_contribution_allocation_plan(
    contribution_usd: float,
    assets: Iterable[ArgentinaAsset],
    policy: LongTermPolicy,
    valuation: Optional[PortfolioValuation] = None,
) -> ContributionAllocationPlan:
    """Produce a clean contribution plan that respects ``min_trade_usd`` and
    ``max_allocations_per_contribution`` from the policy.

    Pipeline:
    1. Generate candidate allocations via the portfolio-aware allocator (which
       internally falls back to the deterministic allocator when no valuation
       is available).
    2. Drop candidates below ``min_trade_usd``; redistribute the skipped USD
       to the retained candidates.
    3. If more than ``max_allocations_per_contribution`` remain, keep the
       largest by ``allocation_usd`` and skip the rest, redistributing again.
    4. If nothing remains, concentrate the contribution into the largest
       original candidate (when ``contribution_usd >= min_trade_usd``) or park
       it in ``CASH_OR_YIELD`` (when ``contribution_usd < min_trade_usd``).
       In both cases, an explanatory warning is added.
    5. Final allocations are normalized to ``contribution_usd`` and sorted by
       ``allocation_usd`` desc.
    """
    contribution = float(contribution_usd)
    if contribution <= 0:
        return ContributionAllocationPlan(
            allocations=tuple(),
            skipped_allocations=tuple(),
            unallocated_usd=0.0,
            warnings=tuple(),
        )

    min_trade = _policy_min_trade_usd(policy)
    max_count = _policy_max_allocations(policy)

    candidates = list(
        allocate_monthly_contribution_with_portfolio(
            contribution, assets, policy, valuation=valuation
        )
    )

    warnings: list[str] = []
    skipped: list[SkippedContributionAllocation] = []

    if not candidates:
        return ContributionAllocationPlan(
            allocations=tuple(),
            skipped_allocations=tuple(),
            unallocated_usd=contribution,
            warnings=(
                "No eligible candidate allocations were produced by the allocator.",
            ),
        )

    # Edge case: contribution itself is below min_trade_usd. Park in cash.
    if contribution < min_trade:
        cash_overweight = _bucket_is_overweight(
            "cash_or_short_term_yield", valuation, policy
        )
        warning = (
            f"Contribution {contribution:.2f} USD below min_trade_usd "
            f"({min_trade:.2f}); parked in cash/yield bucket for manual review."
        )
        if cash_overweight:
            warning += (
                " Note: cash_or_short_term_yield bucket is currently overweight."
            )
        warnings.append(warning)
        skipped = [
            SkippedContributionAllocation(
                symbol=c.symbol,
                asset_class=c.asset_class,
                bucket=c.bucket,
                suggested_usd=c.allocation_usd,
                reason="Contribution below min_trade_usd; redirected to cash/yield.",
            )
            for c in candidates
        ]
        return ContributionAllocationPlan(
            allocations=(
                ContributionAllocation(
                    symbol="CASH_OR_YIELD",
                    asset_class="cash",
                    allocation_usd=contribution,
                    bucket="cash_or_short_term_yield",
                    rationale=(
                        f"Contribution below min_trade_usd ({min_trade:.2f}); "
                        "parked in cash/yield placeholder for manual review."
                    ),
                ),
            ),
            skipped_allocations=tuple(skipped),
            unallocated_usd=0.0,
            warnings=tuple(warnings),
        )

    # Step 2: drop micro-allocations.
    kept: list[ContributionAllocation] = []
    for c in candidates:
        if c.allocation_usd + 1e-9 < min_trade:
            skipped.append(
                SkippedContributionAllocation(
                    symbol=c.symbol,
                    asset_class=c.asset_class,
                    bucket=c.bucket,
                    suggested_usd=c.allocation_usd,
                    reason=(
                        f"Below min_trade_usd threshold "
                        f"({c.allocation_usd:.2f} < {min_trade:.2f})."
                    ),
                )
            )
        else:
            kept.append(c)

    if skipped:
        warnings.append(
            f"Skipped {len(skipped)} allocation(s) below min_trade_usd "
            f"({min_trade:.2f} USD); amounts redistributed to retained "
            "allocations."
        )

    # Step 3: enforce max_allocations_per_contribution.
    if max_count > 0 and len(kept) > max_count:
        # Sort by allocation_usd desc, then symbol asc for determinism on ties.
        kept_sorted = sorted(
            kept, key=lambda a: (-a.allocation_usd, a.symbol)
        )
        retained = kept_sorted[:max_count]
        excess = kept_sorted[max_count:]
        for e in excess:
            skipped.append(
                SkippedContributionAllocation(
                    symbol=e.symbol,
                    asset_class=e.asset_class,
                    bucket=e.bucket,
                    suggested_usd=e.allocation_usd,
                    reason=(
                        "Exceeded max_allocations_per_contribution "
                        f"({max_count})."
                    ),
                )
            )
        warnings.append(
            f"Capped allocations at {max_count}; "
            f"redistributed {len(excess)} skipped allocation(s) to retained set."
        )
        kept = retained

    # Step 4: nothing left -> concentrate or park in cash.
    if not kept:
        if contribution >= min_trade:
            # Concentrate into the largest original candidate (deterministic
            # by allocation_usd desc, then symbol asc).
            top = sorted(
                candidates, key=lambda a: (-a.allocation_usd, a.symbol)
            )[0]
            warnings.append(
                "All candidate allocations were below min_trade_usd; "
                f"concentrated full contribution into top candidate {top.symbol}."
            )
            kept = [
                ContributionAllocation(
                    symbol=top.symbol,
                    asset_class=top.asset_class,
                    allocation_usd=contribution,
                    bucket=top.bucket,
                    rationale=(
                        f"{top.rationale} (Concentrated: all candidate allocations "
                        f"were below min_trade_usd of {min_trade:.2f}.)"
                    ),
                )
            ]
        else:
            cash_overweight = _bucket_is_overweight(
                "cash_or_short_term_yield", valuation, policy
            )
            warning = (
                "All candidate allocations skipped and contribution below "
                "min_trade_usd; parked in cash/yield bucket for manual review."
            )
            if cash_overweight:
                warning += (
                    " Note: cash_or_short_term_yield bucket is currently overweight."
                )
            warnings.append(warning)
            kept = [
                ContributionAllocation(
                    symbol="CASH_OR_YIELD",
                    asset_class="cash",
                    allocation_usd=contribution,
                    bucket="cash_or_short_term_yield",
                    rationale=(
                        "All candidate allocations were below min_trade_usd "
                        "and contribution itself is below threshold; parked in "
                        "cash/yield placeholder for manual review."
                    ),
                )
            ]

    # Step 5: redistribute skipped amount to retained.
    skipped_usd = sum(s.suggested_usd for s in skipped)
    if skipped_usd > 0 and kept and len(kept) > 0:
        # Only redistribute if the kept set didn't already absorb the
        # contribution (concentration / cash branches above use `contribution`
        # directly).
        kept_total = sum(a.allocation_usd for a in kept)
        if kept_total + 1e-9 < contribution:
            kept = _redistribute(kept, contribution - kept_total)

    # Step 6: normalize to contribution total and sort by amount desc.
    kept = _normalize_total(kept, contribution)
    kept_sorted = sorted(
        kept, key=lambda a: (-a.allocation_usd, a.symbol)
    )

    final_total = sum(a.allocation_usd for a in kept_sorted)
    unallocated_usd = max(0.0, contribution - final_total)

    return ContributionAllocationPlan(
        allocations=tuple(kept_sorted),
        skipped_allocations=tuple(skipped),
        unallocated_usd=unallocated_usd,
        warnings=tuple(warnings),
    )


__all__ = [
    "ContributionAllocation",
    "SkippedContributionAllocation",
    "ContributionAllocationPlan",
    "allocate_monthly_contribution",
    "allocate_monthly_contribution_with_portfolio",
    "build_contribution_allocation_plan",
]
