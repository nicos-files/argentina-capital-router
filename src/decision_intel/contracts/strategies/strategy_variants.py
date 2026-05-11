from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.decision_intel.contracts.strategies.strategy_models import StrategyDefinition


class StrategyVariantError(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True)
class StrategyIdentity:
    strategy_id: str
    variant_id: Optional[str] = None

    @property
    def key(self) -> str:
        return f"{self.strategy_id}:{self.variant_id}" if self.variant_id else self.strategy_id


def strategy_identity(definition: StrategyDefinition) -> StrategyIdentity:
    return StrategyIdentity(definition.strategy_id, definition.variant_id)


def require_variant_identity_for_variants(definition: StrategyDefinition) -> None:
    metadata = definition.metadata or {}
    if metadata.get("variant_of") and not definition.variant_id:
        raise StrategyVariantError("MISSING_VARIANT_ID", "variant_id required when metadata.variant_of is set")
