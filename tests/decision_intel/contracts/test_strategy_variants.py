import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.contracts.strategies.strategy_models import StrategyDefinition, StrategyRules
from src.decision_intel.contracts.strategies.strategy_variants import (
    StrategyVariantError,
    strategy_identity,
    require_variant_identity_for_variants,
)


class StrategyVariantsTests(unittest.TestCase):
    def _make_definition(self, variant_id=None, metadata=None):
        return StrategyDefinition(
            schema_version="1.0.0",
            strategy_id="strategy_alpha",
            variant_id=variant_id,
            horizon="SHORT",
            horizon_params=None,
            assumptions={},
            rules=StrategyRules(sizing_rule="size.fixed", constraints=[], filters=[]),
            metadata=metadata,
        )

    def test_strategy_identity_key(self):
        base = self._make_definition()
        self.assertEqual(strategy_identity(base).key, "strategy_alpha")
        variant = self._make_definition(variant_id="v1")
        self.assertEqual(strategy_identity(variant).key, "strategy_alpha:v1")

    def test_variant_identity_required_when_variant_of(self):
        definition = self._make_definition(metadata={"variant_of": "base"})
        with self.assertRaises(StrategyVariantError):
            require_variant_identity_for_variants(definition)


if __name__ == "__main__":
    unittest.main()
