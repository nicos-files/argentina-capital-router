import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_schema():
    schema_path = Path("src/decision_intel/contracts/strategies/strategy_config.schema.json")
    return json.loads(schema_path.read_text(encoding="utf-8"))


class StrategyConfigSchemaTests(unittest.TestCase):
    def test_required_fields_present(self):
        schema = _load_schema()
        required = set(schema["required"])
        expected = {
            "schema_version",
            "strategy_id",
            "horizon",
            "assumptions",
            "rules",
        }
        self.assertTrue(expected.issubset(required))

    def test_schema_version_constant(self):
        schema = _load_schema()
        from src.decision_intel.contracts.strategies.strategy_constants import SCHEMA_VERSION
        self.assertEqual(schema["properties"]["schema_version"]["const"], SCHEMA_VERSION)

    def test_horizon_enum_matches_constants(self):
        schema = _load_schema()
        from src.decision_intel.contracts.strategies.strategy_constants import HORIZON_ENUM
        self.assertEqual(schema["properties"]["horizon"]["enum"], list(HORIZON_ENUM))

    def test_rule_name_pattern_matches_constants(self):
        schema = _load_schema()
        from src.decision_intel.contracts.strategies.strategy_constants import RULE_NAME_PATTERN
        pattern = schema["properties"]["rules"]["properties"]["sizing_rule"]["pattern"]
        self.assertEqual(pattern, RULE_NAME_PATTERN.pattern)

    def test_decision_rules_structure(self):
        schema = _load_schema()
        rules = schema["properties"]["rules"]
        self.assertFalse(rules["additionalProperties"])
        self.assertEqual(set(rules["required"]), {"sizing_rule", "constraints", "filters"})


if __name__ == "__main__":
    unittest.main()
