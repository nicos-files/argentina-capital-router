from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from src.decision_intel.contracts.recommendations.recommendation_models import RecommendationOutput


@dataclass
class EngineContext:
    as_of: datetime
    run_id: str
    mode: str
    universe: list[str]
    prices: Any = None
    fundamentals: Any = None
    positions: Any = None
    cash: float | None = None
    config: dict[str, Any] = field(default_factory=dict)
    provider_health: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EngineDiagnostics:
    engine_name: str
    candidates_seen: int = 0
    candidates_scored: int = 0
    candidates_rejected: int = 0
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EngineResult:
    engine_name: str
    horizon: str
    recommendations: RecommendationOutput
    diagnostics: EngineDiagnostics


@runtime_checkable
class StrategyEngine(Protocol):
    name: str
    horizon: str

    def run(self, context: EngineContext) -> EngineResult:
        ...
