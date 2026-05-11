import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.contracts.strategies.strategy_loader import StrategyConfigError, load_strategy_config


class StrategyLoaderTests(unittest.TestCase):
    def test_load_valid_strategy_config(self):
        fixture = Path("tests/decision_intel/fixtures/strategy_config.example.json")
        strategy = load_strategy_config(fixture)
        self.assertEqual(strategy.strategy_id, "strategy_alpha")
        self.assertEqual(strategy.rules.sizing_rule, "size.fixed")

    def test_missing_rules_fails(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "strategy.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0.0",
                        "strategy_id": "s1",
                        "horizon": "SHORT",
                        "assumptions": {},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(StrategyConfigError) as ctx:
                load_strategy_config(path)
            self.assertEqual(ctx.exception.error_code, "MISSING_RULES")

    def test_invalid_rule_reference_fails(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "strategy.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0.0",
                        "strategy_id": "s1",
                        "horizon": "SHORT",
                        "assumptions": {},
                        "rules": {
                            "sizing_rule": "bad rule()",
                            "constraints": [],
                            "filters": [],
                        },
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(StrategyConfigError) as ctx:
                load_strategy_config(path)
            self.assertEqual(ctx.exception.error_code, "INVALID_RULE_REFERENCE")


if __name__ == "__main__":
    unittest.main()
