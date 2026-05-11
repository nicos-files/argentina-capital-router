from __future__ import annotations

import math
import re
from typing import Any, Dict, Iterable

from src.decision_intel.contracts.decision_policy.policy_constants import (
    READER_MIN_VERSION,
    SCHEMA_VERSION,
)

_METRIC_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")
_DIRECTIONS = {"higher_is_better", "lower_is_better"}


class PolicyValidationError(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _is_finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


def _require_key(data: Dict[str, Any], key: str, error_code: str) -> Any:
    if key not in data:
        raise PolicyValidationError(error_code, f"missing required field: {key}")
    return data[key]


def _validate_thresholds(metric_key: str, thresholds: Dict[str, Any]) -> None:
    if "min" in thresholds and not _is_finite_number(thresholds["min"]):
        raise PolicyValidationError("INVALID_THRESHOLD", f"threshold min must be a finite number for {metric_key}")
    if "max" in thresholds and not _is_finite_number(thresholds["max"]):
        raise PolicyValidationError("INVALID_THRESHOLD", f"threshold max must be a finite number for {metric_key}")
    if "min" in thresholds and "max" in thresholds:
        if thresholds["min"] > thresholds["max"]:
            raise PolicyValidationError("INVALID_THRESHOLD_RANGE", f"threshold min > max for {metric_key}")


def _validate_metric_entries(metrics: Dict[str, Any]) -> None:
    if not metrics:
        raise PolicyValidationError("EMPTY_METRICS", "policy.metrics must be non-empty")
    for key, entry in metrics.items():
        if not _METRIC_KEY_PATTERN.match(key):
            raise PolicyValidationError("INVALID_METRIC_KEY", f"invalid metric key: {key}")
        if not isinstance(entry, dict):
            raise PolicyValidationError("INVALID_METRIC_ENTRY", f"metric entry must be an object: {key}")
        if "weight" not in entry or "direction" not in entry:
            raise PolicyValidationError("MISSING_METRIC_FIELDS", f"metric entry requires weight and direction: {key}")
        if not _is_finite_number(entry["weight"]):
            raise PolicyValidationError("INVALID_WEIGHT", f"weight must be a finite number for {key}")
        if entry["direction"] not in _DIRECTIONS:
            raise PolicyValidationError("INVALID_DIRECTION", f"invalid direction for {key}")
        if "thresholds" in entry:
            thresholds = entry["thresholds"]
            if not isinstance(thresholds, dict):
                raise PolicyValidationError("INVALID_THRESHOLD", f"thresholds must be an object for {key}")
            _validate_thresholds(key, thresholds)


def _reject_unknown_fields(obj: Dict[str, Any], allowed: Iterable[str], label: str) -> None:
    unknown = set(obj.keys()) - set(allowed)
    if unknown:
        raise PolicyValidationError("UNKNOWN_FIELD", f"unexpected fields in {label}: {sorted(unknown)}")


def validate_policy_data(data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(data, dict):
        raise PolicyValidationError("INVALID_POLICY", "policy must be a JSON object")
    _reject_unknown_fields(
        data,
        {"schema_version", "reader_min_version", "policy_id", "description", "metadata", "policy"},
        "policy",
    )
    if data.get("schema_version") != SCHEMA_VERSION:
        raise PolicyValidationError("SCHEMA_VERSION_MISMATCH", "unsupported schema_version")
    if data.get("reader_min_version") != READER_MIN_VERSION:
        raise PolicyValidationError("READER_MIN_VERSION_MISMATCH", "unsupported reader_min_version")
    policy_id = _require_key(data, "policy_id", "MISSING_POLICY_ID")
    if not isinstance(policy_id, str):
        raise PolicyValidationError("INVALID_POLICY_ID", "policy_id must be a string")
    if "description" in data and not isinstance(data["description"], str):
        raise PolicyValidationError("INVALID_DESCRIPTION", "description must be a string")
    if "metadata" in data and not isinstance(data["metadata"], dict):
        raise PolicyValidationError("INVALID_METADATA", "metadata must be an object")

    policy = _require_key(data, "policy", "MISSING_POLICY")
    if not isinstance(policy, dict):
        raise PolicyValidationError("INVALID_POLICY", "policy must be an object")
    _reject_unknown_fields(policy, {"metrics"}, "policy")
    metrics = _require_key(policy, "metrics", "MISSING_METRICS")
    if not isinstance(metrics, dict):
        raise PolicyValidationError("INVALID_METRICS", "policy.metrics must be an object")
    _validate_metric_entries(metrics)
    return data
