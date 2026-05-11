from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from src.decision_intel.contracts.strategies.strategy_models import StrategyDefinition, StrategyRules
from src.decision_intel.contracts.strategies.strategy_constants import (
    HORIZON_ENUM,
    RULE_NAME_PATTERN,
    SCHEMA_VERSION,
)


class StrategyConfigError(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _require_field(obj: Dict[str, Any], field: str, error_code: str) -> Any:
    if field not in obj:
        raise StrategyConfigError(error_code, f"missing required field: {field}")
    return obj[field]


def _validate_rule_name(value: str, field: str) -> None:
    if not isinstance(value, str) or not RULE_NAME_PATTERN.match(value):
        raise StrategyConfigError("INVALID_RULE_REFERENCE", f"invalid rule reference: {field}")


def _validate_rule_list(values: Any, field: str) -> None:
    if not isinstance(values, list):
        raise StrategyConfigError("INVALID_RULE_REFERENCE", f"{field} must be a list of rule references")
    for item in values:
        _validate_rule_name(item, field)


def _validate_schema(data: Dict[str, Any]) -> None:
    if data.get("schema_version") != SCHEMA_VERSION:
        raise StrategyConfigError("SCHEMA_VERSION_MISMATCH", "unsupported schema_version")
    if not isinstance(_require_field(data, "strategy_id", "MISSING_STRATEGY_ID"), str):
        raise StrategyConfigError("INVALID_STRATEGY_ID", "strategy_id must be a string")

    horizon = _require_field(data, "horizon", "MISSING_HORIZON")
    if horizon not in HORIZON_ENUM:
        raise StrategyConfigError("INVALID_HORIZON", "horizon must be one of SHORT, MEDIUM, LONG")

    assumptions = _require_field(data, "assumptions", "MISSING_ASSUMPTIONS")
    if not isinstance(assumptions, dict):
        raise StrategyConfigError("INVALID_ASSUMPTIONS", "assumptions must be an object")

    rules = _require_field(data, "rules", "MISSING_RULES")
    if not isinstance(rules, dict):
        raise StrategyConfigError("INVALID_RULES", "rules must be an object")

    _validate_rule_name(_require_field(rules, "sizing_rule", "MISSING_SIZING_RULE"), "sizing_rule")
    _validate_rule_list(_require_field(rules, "constraints", "MISSING_CONSTRAINTS"), "constraints")
    _validate_rule_list(_require_field(rules, "filters", "MISSING_FILTERS"), "filters")


def load_strategy_config(path: str | Path) -> StrategyDefinition:
    config_path = Path(path)
    data = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise StrategyConfigError("INVALID_CONFIG", "strategy config must be a JSON object")

    _validate_schema(data)

    rules_data = data["rules"]
    rules = StrategyRules(
        sizing_rule=rules_data["sizing_rule"],
        constraints=rules_data["constraints"],
        filters=rules_data["filters"],
    )
    return StrategyDefinition(
        schema_version=data["schema_version"],
        strategy_id=data["strategy_id"],
        variant_id=data.get("variant_id"),
        horizon=data["horizon"],
        horizon_params=data.get("horizon_params"),
        assumptions=data["assumptions"],
        rules=rules,
        metadata=data.get("metadata"),
    )
