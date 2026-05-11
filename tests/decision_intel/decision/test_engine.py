import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.contracts.strategies.strategy_models import StrategyDefinition, StrategyRules
from src.decision_intel.decision.engine import run_decision_engine
from src.decision_intel.decision.rules.builtin import constraint_max_positions, filter_min_liquidity, sizing_fixed
from src.decision_intel.decision.rules.registry import RuleSet


class DecisionEngineTests(unittest.TestCase):
    def test_engine_deterministic(self):
        strategy = StrategyDefinition(
            schema_version="1.0.0",
            strategy_id="strategy_alpha",
            variant_id=None,
            horizon="SHORT",
            horizon_params=None,
            assumptions={},
            rules=StrategyRules(sizing_rule="size.fixed", constraints=[], filters=[]),
            metadata=None,
        )
        rules = RuleSet(
            sizing_rule=sizing_fixed,
            constraints=[constraint_max_positions],
            filters=[filter_min_liquidity],
        )
        signals = [
            {"asset_id": "AAPL", "signal": 0.5},
            {"asset_id": "MSFT", "signal": -0.2},
        ]
        rule_configs = {
            "sizing_rule": {"size": 1.0},
            "constraints": {"max_positions": 10},
            "filters": {"min_liquidity": 1000},
        }
        first = run_decision_engine(strategy, signals, rules, rule_configs)
        second = run_decision_engine(strategy, signals, rules, rule_configs)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
