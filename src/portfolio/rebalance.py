"""Minimal rebalance plan builder. Manual review only. No orders."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


BUY = "BUY"
REDUCE = "REDUCE"
HOLD = "HOLD"


@dataclass(frozen=True)
class RebalanceAction:
    symbol: str
    action: str
    current_pct: float
    target_pct: float
    delta_pct: float
    rationale: str


def build_rebalance_plan(
    current_allocations: Mapping[str, float],
    target_allocations: Mapping[str, float],
    threshold_pct: float = 5.0,
) -> list[RebalanceAction]:
    """Return BUY/REDUCE/HOLD actions per symbol based on absolute pct gap."""
    threshold = float(threshold_pct)
    symbols = set(current_allocations) | set(target_allocations)
    actions: list[RebalanceAction] = []
    for symbol in sorted(symbols):
        current = float(current_allocations.get(symbol, 0.0))
        target = float(target_allocations.get(symbol, 0.0))
        delta = target - current
        if abs(delta) < threshold:
            action = HOLD
            rationale = (
                f"|delta|={abs(delta):.2f}pct below rebalance threshold {threshold:.2f}pct."
            )
        elif delta > 0:
            action = BUY
            rationale = (
                f"Under-weight by {delta:.2f}pct vs target."
            )
        else:
            action = REDUCE
            rationale = (
                f"Over-weight by {abs(delta):.2f}pct vs target."
            )
        actions.append(
            RebalanceAction(
                symbol=symbol,
                action=action,
                current_pct=current,
                target_pct=target,
                delta_pct=delta,
                rationale=rationale,
            )
        )
    return actions


__all__ = ["BUY", "REDUCE", "HOLD", "RebalanceAction", "build_rebalance_plan"]
