import unittest

from src.market_data.ar_symbols import get_enabled_long_term_assets
from src.portfolio.contribution_allocator import allocate_monthly_contribution
from src.portfolio.long_term_policy import load_long_term_policy


class ContributionAllocatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_long_term_policy()
        self.assets = get_enabled_long_term_assets()

    def test_allocates_200_usd(self) -> None:
        allocations = allocate_monthly_contribution(200.0, self.assets, self.policy)
        self.assertGreater(len(allocations), 0)
        total = sum(a.allocation_usd for a in allocations)
        self.assertAlmostEqual(total, 200.0, places=4)

    def test_includes_spy(self) -> None:
        allocations = allocate_monthly_contribution(200.0, self.assets, self.policy)
        self.assertTrue(any(a.symbol == "SPY" for a in allocations))

    def test_zero_contribution_returns_empty(self) -> None:
        self.assertEqual(allocate_monthly_contribution(0.0, self.assets, self.policy), [])

    def test_no_live_trading_or_order_fields(self) -> None:
        allocations = allocate_monthly_contribution(200.0, self.assets, self.policy)
        for alloc in allocations:
            # ContributionAllocation must NOT carry order/broker fields.
            self.assertFalse(hasattr(alloc, "broker"))
            self.assertFalse(hasattr(alloc, "order_type"))
            self.assertFalse(hasattr(alloc, "live_trading_enabled"))


if __name__ == "__main__":
    unittest.main()
