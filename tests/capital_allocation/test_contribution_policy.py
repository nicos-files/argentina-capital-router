import json
import unittest
from pathlib import Path

from src.capital_allocation.contribution_policy import (
    load_contribution_policy,
    validate_contribution_policy,
)


class ContributionPolicyTests(unittest.TestCase):
    def test_load_default(self) -> None:
        policy = load_contribution_policy()
        self.assertTrue(policy.manual_review_only)
        self.assertFalse(policy.live_trading_enabled)
        self.assertEqual(policy.monthly_long_term_contribution_usd, 200.0)

    def test_validate_rejects_live_trading(self) -> None:
        with self.assertRaises(ValueError):
            validate_contribution_policy(
                {
                    "manual_review_only": True,
                    "live_trading_enabled": True,
                    "monthly_long_term_contribution_usd": 200,
                    "max_tactical_duration_days_for_contribution": 10,
                    "max_allowed_loss_pct_on_contribution": 0,
                    "opportunity_thresholds": {
                        "min_expected_net_return_pct": 0.0,
                        "min_score_to_route_capital": 0.0,
                        "max_fx_risk_score": 0.0,
                        "max_liquidity_risk_score": 0.0,
                    },
                    "tactical_bucket": {},
                    "blocked_opportunity_types_for_contribution": [],
                }
            )

    def test_validate_requires_thresholds(self) -> None:
        with self.assertRaises(ValueError):
            validate_contribution_policy(
                {
                    "manual_review_only": True,
                    "live_trading_enabled": False,
                    "monthly_long_term_contribution_usd": 200,
                    "max_tactical_duration_days_for_contribution": 10,
                    "max_allowed_loss_pct_on_contribution": 0,
                    "opportunity_thresholds": {},
                    "tactical_bucket": {},
                    "blocked_opportunity_types_for_contribution": [],
                }
            )

    def test_invalid_path_raises(self) -> None:
        with self.assertRaises(ValueError):
            load_contribution_policy(Path("/nonexistent/policy.json"))


if __name__ == "__main__":
    unittest.main()
