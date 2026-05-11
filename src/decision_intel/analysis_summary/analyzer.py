from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class AnalysisSummary:
    total_metrics: int
    compared_metrics: int
    null_delta_count: int
    null_delta_metrics: List[str]


def summarize_comparison(comparison_metrics: Dict[str, Dict[str, Any]]) -> AnalysisSummary:
    keys = sorted(comparison_metrics.keys())
    null_delta_metrics: List[str] = []
    for key in keys:
        delta = comparison_metrics.get(key, {}).get("delta")
        if delta is None:
            null_delta_metrics.append(key)
    total_metrics = len(keys)
    null_delta_count = len(null_delta_metrics)
    compared_metrics = total_metrics - null_delta_count
    return AnalysisSummary(
        total_metrics=total_metrics,
        compared_metrics=compared_metrics,
        null_delta_count=null_delta_count,
        null_delta_metrics=null_delta_metrics,
    )
