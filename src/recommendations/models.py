"""Recommendation dataclasses for daily capital planning."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence


@dataclass(frozen=True)
class LongTermContributionPlan:
    monthly_contribution_usd: float
    allocations: Sequence[Mapping[str, Any]]
    base_currency: str = "USD"
    notes: str = ""


@dataclass(frozen=True)
class DailyCapitalPlan:
    as_of: str
    manual_review_only: bool
    live_trading_enabled: bool
    monthly_long_term_contribution_usd: float
    routing_decision: Mapping[str, Any]
    long_term_allocations: Sequence[Mapping[str, Any]]
    warnings: Sequence[str] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    market_snapshot_id: Optional[str] = None
    prices_used: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    fx_rates_used: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    rate_inputs_used: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    data_warnings: Sequence[str] = field(default_factory=tuple)
    portfolio_snapshot_id: Optional[str] = None
    portfolio_total_value_usd: Optional[float] = None
    current_bucket_weights: Mapping[str, float] = field(default_factory=dict)
    portfolio_warnings: Sequence[str] = field(default_factory=tuple)
    skipped_allocations: Sequence[Mapping[str, Any]] = field(default_factory=tuple)
    unallocated_usd: float = 0.0
    allocation_warnings: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True)
class CapitalPlanRecommendation:
    """High-level wrapper exposing both the routing decision and the long-term plan."""

    plan: DailyCapitalPlan
    long_term_plan: LongTermContributionPlan


__all__ = [
    "LongTermContributionPlan",
    "DailyCapitalPlan",
    "CapitalPlanRecommendation",
]
