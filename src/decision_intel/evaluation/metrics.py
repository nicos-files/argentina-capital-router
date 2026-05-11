from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Protocol


class MetricsCalculator(Protocol):
    def compute(self, inputs: Dict[str, float]) -> Dict[str, float]:
        ...


@dataclass(frozen=True)
class PassthroughMetricsCalculator:
    """
    Minimal calculator placeholder. Produces deterministic output for tests.
    """

    def compute(self, inputs: Dict[str, float]) -> Dict[str, float]:
        return dict(inputs)


@dataclass(frozen=True)
class DecisionMetricsCalculator:
    """
    Minimal deterministic metrics calculator from decision outputs.
    """

    def compute(self, decisions: Dict[str, float]) -> Dict[str, float]:
        return dict(decisions)
