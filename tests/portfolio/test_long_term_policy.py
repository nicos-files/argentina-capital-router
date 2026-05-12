import unittest

from src.portfolio.long_term_policy import load_long_term_policy, validate_long_term_policy


class LongTermPolicyTests(unittest.TestCase):
    def test_load_default(self) -> None:
        policy = load_long_term_policy()
        self.assertTrue(policy.manual_review_only)
        self.assertFalse(policy.live_trading_enabled)
        self.assertAlmostEqual(sum(policy.target_allocations.values()), 100.0)

    def test_invalid_allocation_sum(self) -> None:
        with self.assertRaises(ValueError):
            validate_long_term_policy(
                {
                    "manual_review_only": True,
                    "live_trading_enabled": False,
                    "default_monthly_contribution_usd": 200,
                    "target_allocations": {
                        "core_global_equity_pct": 60,
                        "cedears_single_names_pct": 20,
                        "argentina_equity_pct": 20,
                        "cash_or_short_term_yield_pct": 10,
                    },
                    "constraints": {
                        "max_single_position_pct": 10,
                        "max_sector_pct": 30,
                        "min_trade_usd": 10,
                        "rebalance_threshold_pct": 5,
                        "cash_reserve_pct": 5,
                    },
                    "risk_buckets": {
                        "low": {"max_total_pct": 80},
                        "medium": {"max_total_pct": 60},
                        "high": {"max_total_pct": 30},
                        "speculative": {"max_total_pct": 10},
                    },
                }
            )


if __name__ == "__main__":
    unittest.main()
