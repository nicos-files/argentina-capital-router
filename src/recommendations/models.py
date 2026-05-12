"""Recommendation dataclasses for daily capital planning."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


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
