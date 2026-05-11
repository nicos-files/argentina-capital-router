import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.contracts.strategies.strategy_validation import validate_strategy_config
from src.decision_intel.contracts.strategies.strategy_loader import StrategyConfigError


class StrategyValidationTests(unittest.TestCase):
    def test_validate_strategy_config_success(self):
        fixture = Path("tests/decision_intel/fixtures/strategy_config.example.json")
        data = validate_strategy_config(fixture)
        self.assertEqual(data["strategy_id"], "strategy_alpha")

    def test_validate_strategy_config_schema_version_fail(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "strategy.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "9.9.9",
                        "strategy_id": "s1",
                        "horizon": "SHORT",
                        "assumptions": {},
                        "rules": {"sizing_rule": "size.fixed", "constraints": [], "filters": []},
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(StrategyConfigError) as ctx:
                validate_strategy_config(path)
            self.assertEqual(ctx.exception.error_code, "SCHEMA_VERSION_MISMATCH")


if __name__ == "__main__":
    unittest.main()
