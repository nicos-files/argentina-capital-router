import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.decision_policy.policy_validator import (
    PolicyValidationError,
    validate_policy_data,
)


def _base_policy():
    return {
        "schema_version": "1.0.0",
        "reader_min_version": "1.0.0",
        "policy_id": "policy-1",
        "policy": {
            "metrics": {
                "return": {"weight": 1.0, "direction": "higher_is_better"},
            }
        },
    }


class PolicyValidationTests(unittest.TestCase):
    def test_valid_policy_passes(self):
        policy = _base_policy()
        validate_policy_data(policy)

    def test_invalid_key_pattern_fails(self):
        policy = _base_policy()
        policy["policy"]["metrics"]["bad key"] = policy["policy"]["metrics"].pop("return")
        with self.assertRaises(PolicyValidationError):
            validate_policy_data(policy)

    def test_invalid_direction_fails(self):
        policy = _base_policy()
        policy["policy"]["metrics"]["return"]["direction"] = "up"
        with self.assertRaises(PolicyValidationError):
            validate_policy_data(policy)

    def test_threshold_min_max_order(self):
        policy = _base_policy()
        policy["policy"]["metrics"]["return"]["thresholds"] = {"min": 2, "max": 1}
        with self.assertRaises(PolicyValidationError):
            validate_policy_data(policy)

    def test_nan_inf_rejected(self):
        policy = _base_policy()
        policy["policy"]["metrics"]["return"]["weight"] = float("nan")
        with self.assertRaises(PolicyValidationError):
            validate_policy_data(policy)

        policy = _base_policy()
        policy["policy"]["metrics"]["return"]["thresholds"] = {"min": float("inf")}
        with self.assertRaises(PolicyValidationError):
            validate_policy_data(policy)


if __name__ == "__main__":
    unittest.main()
