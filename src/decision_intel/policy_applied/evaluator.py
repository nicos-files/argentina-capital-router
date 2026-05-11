from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Optional

from src.decision_intel.decision_policy.policy_validator import validate_policy_data


@dataclass(frozen=True)
class PolicyAppliedResult:
    policy_id: str
    applied_metrics: Dict[str, Dict[str, Any]]


def _is_finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


def _oriented_delta(delta: float, direction: str) -> float:
    if direction == "higher_is_better":
        return delta
    return -delta


def _evaluate_thresholds(value: Optional[float], thresholds: Optional[Dict[str, Any]]) -> Optional[bool]:
    if value is None or thresholds is None:
        return None
    if not _is_finite_number(value):
        return None
    if "min" in thresholds and not _is_finite_number(thresholds["min"]):
        return None
    if "max" in thresholds and not _is_finite_number(thresholds["max"]):
        return None
    if "min" in thresholds and value < thresholds["min"]:
        return False
    if "max" in thresholds and value > thresholds["max"]:
        return False
    return True


def apply_policy_to_comparison(
    policy: Dict[str, Any],
    comparison_metrics: Dict[str, Dict[str, Any]],
) -> PolicyAppliedResult:
    validate_policy_data(policy)
    policy_id = policy["policy_id"]
    metrics_policy = policy["policy"]["metrics"]
    keys = sorted(metrics_policy.keys())
    applied: Dict[str, Dict[str, Any]] = {}
    for key in keys:
        policy_entry = metrics_policy[key]
        comparison_entry = comparison_metrics.get(key, {})
        baseline = comparison_entry.get("baseline")
        candidate = comparison_entry.get("candidate")
        delta = comparison_entry.get("delta")
        direction = policy_entry["direction"]
        weight = policy_entry["weight"]
        thresholds = policy_entry.get("thresholds")
        oriented_delta = None
        weighted_delta = None
        if delta is not None:
            oriented_delta = round(_oriented_delta(delta, direction), 12)
            weighted_delta = round(oriented_delta * weight, 12)
        thresholds_met = _evaluate_thresholds(candidate, thresholds)
        applied[key] = {
            "baseline": baseline,
            "candidate": candidate,
            "delta": delta,
            "direction": direction,
            "weight": weight,
            "thresholds": thresholds,
            "thresholds_met": thresholds_met,
            "oriented_delta": oriented_delta,
            "weighted_delta": weighted_delta,
        }
    return PolicyAppliedResult(policy_id=policy_id, applied_metrics=applied)
