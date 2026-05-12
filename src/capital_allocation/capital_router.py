"""Capital routing decision engine. Manual review only. No orders."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .buckets import CapitalState
from .contribution_policy import ContributionRoutingPolicy


# Routing decision constants
INVEST_DIRECT_LONG_TERM = "INVEST_DIRECT_LONG_TERM"
TACTICAL_THEN_LONG_TERM = "TACTICAL_THEN_LONG_TERM"
DO_NOT_USE_CONTRIBUTION_FOR_TACTICAL = "DO_NOT_USE_CONTRIBUTION_FOR_TACTICAL"
HOLD_CASH_AND_REVIEW = "HOLD_CASH_AND_REVIEW"


@dataclass(frozen=True)
class TacticalOpportunity:
    opportunity_id: str
    opportunity_type: str
    expected_net_return_pct: float
    score: float
    duration_days: int
    fx_risk_score: float
    liquidity_risk_score: float
    uses_leverage: bool = False
    has_clear_exit_date: bool = True
    notes: str = ""


@dataclass(frozen=True)
class CapitalRoutingDecision:
    decision: str
    rationale: str
    manual_review_only: bool = True
    live_trading_enabled: bool = False
    long_term_contribution_protected: bool = True
    tactical_capital_allocated_usd: float = 0.0
    long_term_capital_allocated_usd: float = 0.0
    warnings: tuple = field(default_factory=tuple)
    opportunity_id: Optional[str] = None


def route_capital(
    policy: ContributionRoutingPolicy,
    capital_state: CapitalState,
    opportunity: Optional[TacticalOpportunity] = None,
) -> CapitalRoutingDecision:
    """Decide where capital should go. Never creates orders."""
    contribution = float(capital_state.monthly_long_term_contribution_usd)

    if opportunity is None:
        return CapitalRoutingDecision(
            decision=INVEST_DIRECT_LONG_TERM,
            rationale="No tactical opportunity provided. Route monthly contribution directly to long-term.",
            long_term_capital_allocated_usd=contribution,
            tactical_capital_allocated_usd=0.0,
            warnings=(),
            opportunity_id=None,
        )

    warnings: list[str] = []
    blocked = set(policy.blocked_opportunity_types_for_contribution)

    if opportunity.opportunity_type in blocked:
        return CapitalRoutingDecision(
            decision=DO_NOT_USE_CONTRIBUTION_FOR_TACTICAL,
            rationale=(
                f"Opportunity type {opportunity.opportunity_type!r} is blocked for "
                f"contribution routing by policy."
            ),
            long_term_capital_allocated_usd=contribution,
            tactical_capital_allocated_usd=0.0,
            warnings=tuple(warnings),
            opportunity_id=opportunity.opportunity_id,
        )

    if opportunity.uses_leverage:
        return CapitalRoutingDecision(
            decision=DO_NOT_USE_CONTRIBUTION_FOR_TACTICAL,
            rationale="Opportunity uses leverage; contribution is not eligible.",
            long_term_capital_allocated_usd=contribution,
            tactical_capital_allocated_usd=0.0,
            warnings=tuple(warnings),
            opportunity_id=opportunity.opportunity_id,
        )

    if not opportunity.has_clear_exit_date:
        return CapitalRoutingDecision(
            decision=DO_NOT_USE_CONTRIBUTION_FOR_TACTICAL,
            rationale="Opportunity has no clear exit date; contribution is not eligible.",
            long_term_capital_allocated_usd=contribution,
            tactical_capital_allocated_usd=0.0,
            warnings=tuple(warnings),
            opportunity_id=opportunity.opportunity_id,
        )

    if opportunity.duration_days > policy.max_tactical_duration_days_for_contribution:
        return CapitalRoutingDecision(
            decision=DO_NOT_USE_CONTRIBUTION_FOR_TACTICAL,
            rationale=(
                f"Opportunity duration {opportunity.duration_days}d exceeds policy max "
                f"{policy.max_tactical_duration_days_for_contribution}d for contribution routing."
            ),
            long_term_capital_allocated_usd=contribution,
            tactical_capital_allocated_usd=0.0,
            warnings=tuple(warnings),
            opportunity_id=opportunity.opportunity_id,
        )

    thresholds = policy.opportunity_thresholds
    min_score = float(thresholds.get("min_score_to_route_capital", 0.0))
    min_net_return = float(thresholds.get("min_expected_net_return_pct", 0.0))
    max_fx = float(thresholds.get("max_fx_risk_score", 100.0))
    max_liq = float(thresholds.get("max_liquidity_risk_score", 100.0))

    if opportunity.score < min_score or opportunity.expected_net_return_pct < min_net_return:
        return CapitalRoutingDecision(
            decision=INVEST_DIRECT_LONG_TERM,
            rationale=(
                f"Opportunity score {opportunity.score:.1f} or expected net return "
                f"{opportunity.expected_net_return_pct:.2f}% below policy thresholds; "
                "route contribution to long-term."
            ),
            long_term_capital_allocated_usd=contribution,
            tactical_capital_allocated_usd=0.0,
            warnings=tuple(warnings),
            opportunity_id=opportunity.opportunity_id,
        )

    fx_high = opportunity.fx_risk_score > max_fx
    liq_high = opportunity.liquidity_risk_score > max_liq

    if fx_high or liq_high:
        if fx_high:
            warnings.append(
                f"FX risk score {opportunity.fx_risk_score:.1f} above policy max {max_fx:.1f}."
            )
        if liq_high:
            warnings.append(
                f"Liquidity risk score {opportunity.liquidity_risk_score:.1f} above policy max {max_liq:.1f}."
            )
        # If both risks too high, hold cash and review.
        if fx_high and liq_high:
            return CapitalRoutingDecision(
                decision=HOLD_CASH_AND_REVIEW,
                rationale=(
                    "Both FX and liquidity risk above policy maxima; hold cash and review manually."
                ),
                long_term_capital_allocated_usd=0.0,
                tactical_capital_allocated_usd=0.0,
                warnings=tuple(warnings),
                opportunity_id=opportunity.opportunity_id,
            )
        return CapitalRoutingDecision(
            decision=INVEST_DIRECT_LONG_TERM,
            rationale=(
                "Opportunity risk score exceeds policy maxima; route contribution to long-term."
            ),
            long_term_capital_allocated_usd=contribution,
            tactical_capital_allocated_usd=0.0,
            warnings=tuple(warnings),
            opportunity_id=opportunity.opportunity_id,
        )

    if not policy.can_temporarily_use_contribution_for_tactical_opportunities:
        return CapitalRoutingDecision(
            decision=INVEST_DIRECT_LONG_TERM,
            rationale=(
                "Policy does not allow temporary tactical use of contribution. "
                "Route directly to long-term."
            ),
            long_term_capital_allocated_usd=contribution,
            tactical_capital_allocated_usd=0.0,
            warnings=tuple(warnings),
            opportunity_id=opportunity.opportunity_id,
        )

    # Valid opportunity: temporarily route contribution through tactical bucket,
    # then back to long-term. Long-term contribution remains conceptually protected:
    # losses absorb on tactical_bucket first per policy.
    tactical_allocation = contribution + float(
        capital_state.tactical_bucket.available_usd
    )
    return CapitalRoutingDecision(
        decision=TACTICAL_THEN_LONG_TERM,
        rationale=(
            "Tactical opportunity passes thresholds; temporarily route contribution through "
            "tactical bucket, then release to long-term by end of month. Manual review required."
        ),
        long_term_contribution_protected=True,
        tactical_capital_allocated_usd=tactical_allocation,
        long_term_capital_allocated_usd=0.0,
        warnings=tuple(warnings),
        opportunity_id=opportunity.opportunity_id,
    )


__all__ = [
    "INVEST_DIRECT_LONG_TERM",
    "TACTICAL_THEN_LONG_TERM",
    "DO_NOT_USE_CONTRIBUTION_FOR_TACTICAL",
    "HOLD_CASH_AND_REVIEW",
    "TacticalOpportunity",
    "CapitalRoutingDecision",
    "route_capital",
]
