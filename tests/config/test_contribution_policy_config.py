import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = REPO_ROOT / "config" / "capital_routing" / "contribution_policy.json"


class ContributionPolicyConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.data = json.loads(POLICY_PATH.read_text(encoding="utf-8"))

    def test_config_exists(self) -> None:
        self.assertTrue(POLICY_PATH.exists())

    def test_manual_review_and_no_live_trading(self) -> None:
        self.assertIs(self.data["manual_review_only"], True)
        self.assertIs(self.data["live_trading_enabled"], False)

    def test_monthly_contribution_is_200(self) -> None:
        self.assertEqual(self.data["monthly_long_term_contribution_usd"], 200)

    def test_blocked_opportunity_types(self) -> None:
        blocked = set(self.data["blocked_opportunity_types_for_contribution"])
        self.assertIn("leveraged_trade", blocked)
        self.assertIn("unknown_exit_date", blocked)


if __name__ == "__main__":
    unittest.main()
