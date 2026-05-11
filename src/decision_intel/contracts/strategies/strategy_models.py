from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Literal


@dataclass(frozen=True)
class StrategyRules:
    sizing_rule: str
    constraints: List[str]
    filters: List[str]


@dataclass(frozen=True)
class StrategyDefinition:
    schema_version: str
    strategy_id: str
    variant_id: Optional[str]
    horizon: Literal["SHORT", "MEDIUM", "LONG"]
    horizon_params: Optional[Dict[str, Any]]
    assumptions: Dict[str, Any]
    rules: StrategyRules
    metadata: Optional[Dict[str, Any]]
