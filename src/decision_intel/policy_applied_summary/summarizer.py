from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class PolicyAppliedSummary:
    total_policy_metrics: int
    metrics_with_null_delta: int
    metrics_with_non_null_delta: int
    thresholds_defined_count: int
    thresholds_met_count: int
    thresholds_failed_count: int
    thresholds_unknown_count: int
    oriented_delta_positive_count: int
    oriented_delta_negative_count: int
    oriented_delta_zero_count: int
    oriented_delta_null_count: int
    null_delta_metrics: List[str]
    thresholds_failed_metrics: List[str]
    thresholds_unknown_metrics: List[str]


def summarize_policy_applied(
    policy_applied_metrics: Dict[str, Dict[str, Any]],
) -> PolicyAppliedSummary:
    keys = sorted(policy_applied_metrics.keys())
    null_delta_metrics: List[str] = []
    thresholds_failed_metrics: List[str] = []
    thresholds_unknown_metrics: List[str] = []
    metrics_with_null_delta = 0
    thresholds_defined_count = 0
    thresholds_met_count = 0
    thresholds_failed_count = 0
    thresholds_unknown_count = 0
    oriented_delta_positive_count = 0
    oriented_delta_negative_count = 0
    oriented_delta_zero_count = 0
    oriented_delta_null_count = 0

    for key in keys:
        entry = policy_applied_metrics.get(key, {})
        delta = entry.get("delta")
        oriented_delta = entry.get("oriented_delta")
        thresholds = entry.get("thresholds")
        thresholds_met = entry.get("thresholds_met")

        if delta is None:
            metrics_with_null_delta += 1
            null_delta_metrics.append(key)

        if thresholds is not None:
            thresholds_defined_count += 1
            if thresholds_met is True:
                thresholds_met_count += 1
            elif thresholds_met is False:
                thresholds_failed_count += 1
                thresholds_failed_metrics.append(key)
            else:
                thresholds_unknown_count += 1
                thresholds_unknown_metrics.append(key)

        if oriented_delta is None:
            oriented_delta_null_count += 1
        else:
            if oriented_delta > 0:
                oriented_delta_positive_count += 1
            elif oriented_delta < 0:
                oriented_delta_negative_count += 1
            else:
                oriented_delta_zero_count += 1

    total_policy_metrics = len(keys)
    metrics_with_non_null_delta = total_policy_metrics - metrics_with_null_delta
    return PolicyAppliedSummary(
        total_policy_metrics=total_policy_metrics,
        metrics_with_null_delta=metrics_with_null_delta,
        metrics_with_non_null_delta=metrics_with_non_null_delta,
        thresholds_defined_count=thresholds_defined_count,
        thresholds_met_count=thresholds_met_count,
        thresholds_failed_count=thresholds_failed_count,
        thresholds_unknown_count=thresholds_unknown_count,
        oriented_delta_positive_count=oriented_delta_positive_count,
        oriented_delta_negative_count=oriented_delta_negative_count,
        oriented_delta_zero_count=oriented_delta_zero_count,
        oriented_delta_null_count=oriented_delta_null_count,
        null_delta_metrics=null_delta_metrics,
        thresholds_failed_metrics=thresholds_failed_metrics,
        thresholds_unknown_metrics=thresholds_unknown_metrics,
    )
