"""Carry trade scanner.

Offline-only scoring. Not a real recommendation engine. Manual review only.
"""
from __future__ import annotations

from dataclasses import dataclass, field


ATTRACTIVE = "ATTRACTIVE"
MODERATE = "MODERATE"
WEAK = "WEAK"
AVOID = "AVOID"


@dataclass(frozen=True)
class CarryInputs:
    opportunity_id: str
    expected_monthly_rate_pct: float
    expected_fx_devaluation_pct: float
    estimated_cost_pct: float
    duration_days: int
    fx_risk_score: float
    liquidity_risk_score: float
    notes: str = ""


@dataclass(frozen=True)
class CarryScore:
    opportunity_id: str
    expected_net_return_pct: float
    score: float
    classification: str
    warnings: tuple = field(default_factory=tuple)
    inputs: CarryInputs | None = None


def _classify(score: float, expected_net_return_pct: float) -> str:
    if score >= 75 and expected_net_return_pct > 0:
        return ATTRACTIVE
    if score >= 55 and expected_net_return_pct > 0:
        return MODERATE
    if score >= 35:
        return WEAK
    return AVOID


def score_carry_opportunity(inputs: CarryInputs) -> CarryScore:
    expected_net_return_pct = (
        float(inputs.expected_monthly_rate_pct)
        - float(inputs.expected_fx_devaluation_pct)
        - float(inputs.estimated_cost_pct)
    )

    # Base score: each +1 pct net return contributes 8 points, capped.
    base = 50.0 + (expected_net_return_pct * 8.0)

    # Risk penalties.
    fx_risk = float(inputs.fx_risk_score)
    liq_risk = float(inputs.liquidity_risk_score)
    fx_penalty = max(0.0, (fx_risk - 50.0)) * 0.5
    liq_penalty = max(0.0, (liq_risk - 50.0)) * 0.4
    duration_penalty = max(0, int(inputs.duration_days) - 10) * 1.0

    score = base - fx_penalty - liq_penalty - duration_penalty
    score = max(0.0, min(100.0, score))

    warnings: list[str] = []
    if fx_risk >= 70:
        warnings.append(f"high FX risk (score={fx_risk:.1f})")
    if liq_risk >= 70:
        warnings.append(f"high liquidity risk (score={liq_risk:.1f})")
    if expected_net_return_pct <= 0:
        warnings.append(
            f"non-positive expected net return ({expected_net_return_pct:.2f}%)"
        )

    classification = _classify(score, expected_net_return_pct)

    return CarryScore(
        opportunity_id=inputs.opportunity_id,
        expected_net_return_pct=expected_net_return_pct,
        score=score,
        classification=classification,
        warnings=tuple(warnings),
        inputs=inputs,
    )


__all__ = [
    "ATTRACTIVE",
    "MODERATE",
    "WEAK",
    "AVOID",
    "CarryInputs",
    "CarryScore",
    "score_carry_opportunity",
]
