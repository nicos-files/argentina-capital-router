from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class ComparisonResult:
    baseline_metrics: Dict[str, Optional[float]]
    candidate_metrics: Dict[str, Optional[float]]
    deltas: Dict[str, Optional[float]]


def compare_normalized(
    baseline: Dict[str, Optional[float]],
    candidate: Dict[str, Optional[float]],
) -> ComparisonResult:
    keys = sorted(set(baseline.keys()) | set(candidate.keys()))
    baseline_out: Dict[str, Optional[float]] = {}
    candidate_out: Dict[str, Optional[float]] = {}
    deltas: Dict[str, Optional[float]] = {}
    for key in keys:
        b = baseline.get(key)
        c = candidate.get(key)
        baseline_out[key] = b
        candidate_out[key] = c
        if b is None or c is None:
            deltas[key] = None
        else:
            deltas[key] = round(c - b, 12)
    return ComparisonResult(baseline_out, candidate_out, deltas)
