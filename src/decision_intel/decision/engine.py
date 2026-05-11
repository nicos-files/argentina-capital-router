from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from src.decision_intel.contracts.strategies.strategy_models import StrategyDefinition
from src.decision_intel.decision.rules.registry import RuleSet, merge_rule_outputs


@dataclass(frozen=True)
class DecisionOutput:
    asset_id: str
    signal: float
    outputs: Dict[str, Any]


def run_decision_engine(
    strategy: StrategyDefinition,
    signals: List[Dict[str, Any]],
    rules: RuleSet,
    rule_configs: Dict[str, Dict[str, Any]],
) -> List[DecisionOutput]:
    """
    Pure, deterministic decision engine. Applies rule set to each signal record.
    """
    decisions: List[DecisionOutput] = []
    sizing_cfg = rule_configs.get("sizing_rule", {})
    constraints_cfg = rule_configs.get("constraints", {})
    filters_cfg = rule_configs.get("filters", {})

    for signal in signals:
        context = {"strategy": strategy, "signal": signal}
        outputs = []
        outputs.append(rules.sizing_rule(context, sizing_cfg))
        for fn in rules.constraints:
            outputs.append(fn(context, constraints_cfg))
        for fn in rules.filters:
            outputs.append(fn(context, filters_cfg))
        merged = merge_rule_outputs(outputs)
        decisions.append(
            DecisionOutput(
                asset_id=signal["asset_id"],
                signal=signal["signal"],
                outputs=merged,
            )
        )
    return decisions
