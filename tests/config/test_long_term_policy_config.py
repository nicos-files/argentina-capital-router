import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = REPO_ROOT / "config" / "portfolio" / "long_term_policy.json"


class LongTermPolicyConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = json.loads(POLICY_PATH.read_text(encoding="utf-8"))

    def test_config_exists(self) -> None:
        self.assertTrue(POLICY_PATH.exists())

    def test_target_allocations_sum_to_100(self) -> None:
        total = sum(self.data["target_allocations"].values())
        self.assertAlmostEqual(total, 100.0)

    def test_manual_review_and_no_live_trading(self) -> None:
        self.assertIs(self.data["manual_review_only"], True)
        self.assertIs(self.data["live_trading_enabled"], False)

    def test_min_trade_usd_present_and_non_negative(self) -> None:
        constraints = self.data["constraints"]
        self.assertIn("min_trade_usd", constraints)
        self.assertGreaterEqual(float(constraints["min_trade_usd"]), 0.0)

    def test_max_allocations_per_contribution_present_and_positive(self) -> None:
        constraints = self.data["constraints"]
        self.assertIn("max_allocations_per_contribution", constraints)
        value = int(constraints["max_allocations_per_contribution"])
        self.assertGreater(value, 0)


if __name__ == "__main__":
    unittest.main()
