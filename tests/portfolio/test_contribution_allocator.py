import unittest

from src.market_data.ar_symbols import get_enabled_long_term_assets
from src.portfolio.contribution_allocator import (
    allocate_monthly_contribution,
    allocate_monthly_contribution_with_portfolio,
)
from src.portfolio.long_term_policy import load_long_term_policy
from src.portfolio.portfolio_valuation import PortfolioValuation


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


def _make_valuation(bucket_weights: dict, total_usd: float = 1000.0) -> PortfolioValuation:
    return PortfolioValuation(
        as_of="2026-05-12",
        base_currency="USD",
        total_value_usd=total_usd,
        positions=tuple(),
        cash=tuple(),
        bucket_weights=bucket_weights,
        warnings=tuple(),
    )


class PortfolioAwareAllocatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_long_term_policy()
        self.assets = get_enabled_long_term_assets()
        # Policy targets:
        # core 50, cedears 20, argentina 20, cash 10

    def test_falls_back_to_default_when_no_valuation(self) -> None:
        default = allocate_monthly_contribution(200.0, self.assets, self.policy)
        with_none = allocate_monthly_contribution_with_portfolio(
            200.0, self.assets, self.policy, valuation=None
        )
        self.assertEqual(
            [(a.symbol, round(a.allocation_usd, 6)) for a in with_none],
            [(a.symbol, round(a.allocation_usd, 6)) for a in default],
        )

    def test_underweight_core_global_equity_prioritizes_spy(self) -> None:
        # Argentina overweight, core underweight.
        valuation = _make_valuation(
            {
                "core_global_equity": 10.0,        # target 50 -> +40
                "cedears_single_names": 20.0,      # target 20 -> 0
                "argentina_equity": 60.0,          # target 20 -> -40 overweight
                "cash_or_short_term_yield": 10.0,  # target 10 -> 0
            }
        )
        allocations = allocate_monthly_contribution_with_portfolio(
            200.0, self.assets, self.policy, valuation=valuation
        )
        total = sum(a.allocation_usd for a in allocations)
        self.assertAlmostEqual(total, 200.0, places=4)
        # SPY (core bucket) must receive the entire contribution since it is
        # the only underweight bucket.
        symbols = {a.symbol for a in allocations}
        self.assertEqual(symbols, {"SPY"})
        self.assertTrue(any("core_global_equity" in a.rationale for a in allocations))

    def test_overweight_argentina_avoids_ar_equities_when_possible(self) -> None:
        valuation = _make_valuation(
            {
                "core_global_equity": 20.0,        # target 50 -> +30 (underweight)
                "cedears_single_names": 10.0,      # target 20 -> +10 (underweight)
                "argentina_equity": 60.0,          # target 20 -> -40 overweight
                "cash_or_short_term_yield": 10.0,  # target 10 -> 0 at target
            }
        )
        allocations = allocate_monthly_contribution_with_portfolio(
            200.0, self.assets, self.policy, valuation=valuation
        )
        total = sum(a.allocation_usd for a in allocations)
        self.assertAlmostEqual(total, 200.0, places=4)
        # Argentina equities must NOT be funded while argentina_equity is overweight.
        ar_buckets = {a.bucket for a in allocations}
        self.assertNotIn("argentina_equity", ar_buckets)

    def test_underweight_cash_routes_to_cash_pseudo_symbol(self) -> None:
        valuation = _make_valuation(
            {
                "core_global_equity": 50.0,        # target 50 -> 0
                "cedears_single_names": 20.0,      # target 20 -> 0
                "argentina_equity": 30.0,          # target 20 -> -10 overweight
                "cash_or_short_term_yield": 0.0,   # target 10 -> +10 underweight
            }
        )
        allocations = allocate_monthly_contribution_with_portfolio(
            200.0, self.assets, self.policy, valuation=valuation
        )
        total = sum(a.allocation_usd for a in allocations)
        self.assertAlmostEqual(total, 200.0, places=4)
        symbols = {a.symbol for a in allocations}
        self.assertEqual(symbols, {"CASH_OR_YIELD"})

    def test_exactly_at_target_falls_through_to_least_overweight_branch(self) -> None:
        # When every policy bucket sits exactly at target, no bucket is strictly
        # underweight and the allocator falls through to the "least-overweight"
        # branch. With all deltas == 0, the deterministic tiebreak prefers the
        # first policy bucket (core_global_equity -> SPY).
        valuation = _make_valuation(
            {
                "core_global_equity": 50.0,
                "cedears_single_names": 20.0,
                "argentina_equity": 20.0,
                "cash_or_short_term_yield": 10.0,
            }
        )
        allocations = allocate_monthly_contribution_with_portfolio(
            200.0, self.assets, self.policy, valuation=valuation
        )
        total = sum(a.allocation_usd for a in allocations)
        self.assertAlmostEqual(total, 200.0, places=4)
        symbols = {a.symbol for a in allocations}
        self.assertEqual(symbols, {"SPY"})
        self.assertTrue(any("at/above policy" in a.rationale for a in allocations))

    def test_zero_total_value_falls_back_to_default(self) -> None:
        valuation = _make_valuation({}, total_usd=0.0)
        allocations = allocate_monthly_contribution_with_portfolio(
            200.0, self.assets, self.policy, valuation=valuation
        )
        # Same as no-valuation default allocator.
        default = allocate_monthly_contribution(200.0, self.assets, self.policy)
        self.assertEqual(
            [(a.symbol, round(a.allocation_usd, 6)) for a in allocations],
            [(a.symbol, round(a.allocation_usd, 6)) for a in default],
        )


if __name__ == "__main__":
    unittest.main()
