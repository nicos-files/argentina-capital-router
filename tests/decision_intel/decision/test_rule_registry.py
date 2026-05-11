import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.decision.rules.builtin import (
    constraint_max_positions,
    filter_min_liquidity,
    sizing_fixed,
)
from src.decision_intel.decision.rules.registry import RuleRegistry, RuleRegistryError, merge_rule_outputs


class RuleRegistryTests(unittest.TestCase):
    def test_resolve_rules(self):
        registry = RuleRegistry()
        registry.register_sizing("size.fixed", sizing_fixed)
        registry.register_constraint("risk.max_positions", constraint_max_positions)
        registry.register_filter("eligibility.liquid", filter_min_liquidity)

        resolved = registry.resolve(
            sizing_rule="size.fixed",
            constraints=["risk.max_positions"],
            filters=["eligibility.liquid"],
        )
        self.assertTrue(callable(resolved.sizing_rule))
        self.assertEqual(len(resolved.constraints), 1)
        self.assertEqual(len(resolved.filters), 1)

    def test_missing_rule_error(self):
        registry = RuleRegistry()
        with self.assertRaises(RuleRegistryError) as ctx:
            registry.resolve("size.fixed", [], [])
        self.assertEqual(ctx.exception.error_code, "MISSING_SIZING_RULE")

    def test_merge_rule_outputs_deterministic(self):
        merged = merge_rule_outputs([{"a": 1, "b": 1}, {"b": 2}, {"c": 3}])
        self.assertEqual(merged, {"a": 1, "b": 2, "c": 3})


if __name__ == "__main__":
    unittest.main()
