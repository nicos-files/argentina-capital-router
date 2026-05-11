from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple


@dataclass(frozen=True)
class NormalizationResult:
    metrics_by_horizon: Dict[str, Dict[str, float]]
    normalized_metrics: Dict[str, float]
    method: str
    params: Dict[str, float]


def normalize_mean(metrics_by_horizon: Dict[str, Dict[str, float]]) -> NormalizationResult:
    """
    Deterministic normalization: mean across horizons for each metric key.
    """
    if not metrics_by_horizon:
        return NormalizationResult({}, {}, "mean", {})
    keys: List[str] = sorted({k for m in metrics_by_horizon.values() for k in m.keys()})
    normalized: Dict[str, float] = {}
    for key in keys:
        values: List[float] = []
        for horizon in sorted(metrics_by_horizon.keys()):
            if key in metrics_by_horizon[horizon]:
                values.append(metrics_by_horizon[horizon][key])
        if values:
            normalized[key] = sum(values) / len(values)
    return NormalizationResult(metrics_by_horizon, normalized, "mean", {})
