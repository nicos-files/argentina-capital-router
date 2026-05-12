"""Carry trade scanner.

Offline-only scoring. Not a real recommendation engine. Manual review only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from src.market_data.manual_snapshot import ManualMarketSnapshot


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


def build_carry_inputs_from_snapshot(
    snapshot: "ManualMarketSnapshot",
    rate_key: str = "money_market_monthly_pct",
    expected_fx_key: str = "expected_fx_devaluation_monthly_pct",
    estimated_cost_pct: float = 0.2,
    duration_days: int = 7,
    fx_risk_score: float = 50.0,
    liquidity_risk_score: float = 40.0,
    opportunity_id: str = "snapshot_carry",
    notes: str = "",
) -> CarryInputs:
    """Build :class:`CarryInputs` from a manual market snapshot.

    No network. No financial advice. Manual review only.

    Raises:
        ValueError: if the snapshot is missing either the expected monthly rate
            entry under ``rate_key`` or the expected FX devaluation entry under
            ``expected_fx_key``.
    """
    from src.market_data.manual_snapshot import get_rate_input

    rate_entry = get_rate_input(snapshot, rate_key)
    if rate_entry is None:
        raise ValueError(
            f"snapshot is missing rate key {rate_key!r}; "
            "cannot build carry inputs."
        )
    fx_entry = get_rate_input(snapshot, expected_fx_key)
    if fx_entry is None:
        raise ValueError(
            f"snapshot is missing expected FX devaluation key {expected_fx_key!r}; "
            "cannot build carry inputs."
        )

    derived_notes = notes or (
        f"Built from snapshot {snapshot.snapshot_id} as_of {snapshot.as_of}; "
        f"rate_key={rate_key}; expected_fx_key={expected_fx_key}."
    )

    return CarryInputs(
        opportunity_id=str(opportunity_id),
        expected_monthly_rate_pct=float(rate_entry.value),
        expected_fx_devaluation_pct=float(fx_entry.value),
        estimated_cost_pct=float(estimated_cost_pct),
        duration_days=int(duration_days),
        fx_risk_score=float(fx_risk_score),
        liquidity_risk_score=float(liquidity_risk_score),
        notes=derived_notes,
    )


__all__ = [
    "ATTRACTIVE",
    "MODERATE",
    "WEAK",
    "AVOID",
    "CarryInputs",
    "CarryScore",
    "score_carry_opportunity",
    "build_carry_inputs_from_snapshot",
]
