from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List


RuleFn = Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]


@dataclass(frozen=True)
class RuleSet:
    sizing_rule: RuleFn
    constraints: List[RuleFn]
    filters: List[RuleFn]


class RuleRegistryError(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class RuleRegistry:
    def __init__(self) -> None:
        self._sizing: Dict[str, RuleFn] = {}
        self._constraints: Dict[str, RuleFn] = {}
        self._filters: Dict[str, RuleFn] = {}

    def register_sizing(self, name: str, fn: RuleFn) -> None:
        self._sizing[name] = fn

    def register_constraint(self, name: str, fn: RuleFn) -> None:
        self._constraints[name] = fn

    def register_filter(self, name: str, fn: RuleFn) -> None:
        self._filters[name] = fn

    def resolve(
        self,
        sizing_rule: str,
        constraints: List[str],
        filters: List[str],
    ) -> RuleSet:
        if sizing_rule not in self._sizing:
            raise RuleRegistryError("MISSING_SIZING_RULE", f"unknown sizing_rule: {sizing_rule}")
        missing_constraints = [name for name in constraints if name not in self._constraints]
        if missing_constraints:
            raise RuleRegistryError("MISSING_CONSTRAINT_RULE", f"unknown constraints: {missing_constraints}")
        missing_filters = [name for name in filters if name not in self._filters]
        if missing_filters:
            raise RuleRegistryError("MISSING_FILTER_RULE", f"unknown filters: {missing_filters}")
        return RuleSet(
            sizing_rule=self._sizing[sizing_rule],
            constraints=[self._constraints[name] for name in constraints],
            filters=[self._filters[name] for name in filters],
        )


def merge_rule_outputs(outputs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Merge partial rule outputs deterministically. Later rules override earlier keys.
    """
    merged: Dict[str, Any] = {}
    for output in outputs:
        merged.update(output)
    return merged
