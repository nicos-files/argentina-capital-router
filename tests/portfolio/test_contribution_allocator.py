import unittest

from src.market_data.ar_symbols import get_enabled_long_term_assets
from src.portfolio.contribution_allocator import (
    ContributionAllocationPlan,
    SkippedContributionAllocation,
    allocate_monthly_contribution,
    allocate_monthly_contribution_with_portfolio,
    build_contribution_allocation_plan,
)
from src.portfolio.long_term_policy import LongTermPolicy, load_long_term_policy
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


def _make_policy_with_constraints(
    base: LongTermPolicy, **overrides: float | int
) -> LongTermPolicy:
    constraints = dict(base.constraints)
    constraints.update({k: v for k, v in overrides.items()})
    return LongTermPolicy(
        schema_version=base.schema_version,
        policy_id=base.policy_id,
        base_currency=base.base_currency,
        manual_review_only=base.manual_review_only,
        live_trading_enabled=base.live_trading_enabled,
        default_monthly_contribution_usd=base.default_monthly_contribution_usd,
        target_allocations=base.target_allocations,
        constraints=constraints,
        risk_buckets=base.risk_buckets,
        raw=base.raw,
    )


class BuildContributionAllocationPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_long_term_policy()
        self.assets = get_enabled_long_term_assets()

    def test_returns_plan_with_no_micro_allocations(self) -> None:
        plan = build_contribution_allocation_plan(200.0, self.assets, self.policy)
        self.assertIsInstance(plan, ContributionAllocationPlan)
        min_trade = float(self.policy.constraints["min_trade_usd"])
        for a in plan.allocations:
            self.assertGreaterEqual(a.allocation_usd + 1e-9, min_trade)

    def test_skipped_allocations_have_reason(self) -> None:
        # Default allocator splits argentina_equity bucket across 6 names from
        # USD 200 contribution -> each ~6.67 USD, below min_trade_usd=10.
        plan = build_contribution_allocation_plan(200.0, self.assets, self.policy)
        self.assertGreater(len(plan.skipped_allocations), 0)
        for s in plan.skipped_allocations:
            self.assertIsInstance(s, SkippedContributionAllocation)
            self.assertTrue(s.reason)

    def test_total_remains_approximately_contribution(self) -> None:
        plan = build_contribution_allocation_plan(200.0, self.assets, self.policy)
        total = sum(a.allocation_usd for a in plan.allocations)
        self.assertAlmostEqual(total + plan.unallocated_usd, 200.0, places=4)

    def test_max_allocations_per_contribution_enforced(self) -> None:
        policy = _make_policy_with_constraints(
            self.policy, max_allocations_per_contribution=2
        )
        plan = build_contribution_allocation_plan(200.0, self.assets, policy)
        self.assertLessEqual(len(plan.allocations), 2)
        # Anything beyond the cap should be skipped with the relevant reason.
        capped_reasons = [
            s for s in plan.skipped_allocations
            if "Exceeded max_allocations_per_contribution" in s.reason
        ]
        self.assertGreaterEqual(len(capped_reasons), 1)

    def test_warnings_mention_thresholds(self) -> None:
        plan = build_contribution_allocation_plan(200.0, self.assets, self.policy)
        joined = " | ".join(plan.warnings)
        self.assertIn("min_trade_usd", joined)

    def test_contribution_below_min_trade_parks_in_cash(self) -> None:
        # min_trade_usd=10 in policy. Contribute 5 USD.
        plan = build_contribution_allocation_plan(5.0, self.assets, self.policy)
        self.assertEqual(len(plan.allocations), 1)
        self.assertEqual(plan.allocations[0].symbol, "CASH_OR_YIELD")
        self.assertEqual(plan.allocations[0].bucket, "cash_or_short_term_yield")
        self.assertAlmostEqual(plan.allocations[0].allocation_usd, 5.0, places=6)
        self.assertTrue(
            any("below min_trade_usd" in w for w in plan.warnings),
            f"warnings={plan.warnings}",
        )

    def test_all_candidates_below_threshold_concentrates_into_top(self) -> None:
        # With min_trade_usd very high, every default allocation will be below
        # threshold. Contribution itself (200) >= min_trade (50) => concentrate.
        policy = _make_policy_with_constraints(self.policy, min_trade_usd=150.0)
        plan = build_contribution_allocation_plan(200.0, self.assets, policy)
        self.assertEqual(len(plan.allocations), 1)
        # Total preserved.
        total = sum(a.allocation_usd for a in plan.allocations)
        self.assertAlmostEqual(total, 200.0, places=4)
        # Top candidate from the default allocator is SPY (100 USD for core).
        self.assertEqual(plan.allocations[0].symbol, "SPY")
        self.assertTrue(
            any("concentrated" in w.lower() for w in plan.warnings),
            f"warnings={plan.warnings}",
        )

    def test_fallback_no_valuation_still_works(self) -> None:
        # With valuation=None and default policy, plan should produce >=1
        # allocations summing to ~200 USD.
        plan = build_contribution_allocation_plan(
            200.0, self.assets, self.policy, valuation=None
        )
        self.assertGreater(len(plan.allocations), 0)
        total = sum(a.allocation_usd for a in plan.allocations)
        self.assertAlmostEqual(total + plan.unallocated_usd, 200.0, places=4)

    def test_portfolio_aware_prioritizes_underweight_buckets(self) -> None:
        # core underweight (10 vs target 50); cedears underweight (10 vs 20);
        # argentina overweight (60 vs 20); cash at target (10 vs 10).
        valuation = PortfolioValuation(
            as_of="2026-05-12",
            base_currency="USD",
            total_value_usd=1000.0,
            positions=tuple(),
            cash=tuple(),
            bucket_weights={
                "core_global_equity": 10.0,
                "cedears_single_names": 10.0,
                "argentina_equity": 60.0,
                "cash_or_short_term_yield": 20.0,
            },
            warnings=tuple(),
        )
        plan = build_contribution_allocation_plan(
            200.0, self.assets, self.policy, valuation=valuation
        )
        buckets = {a.bucket for a in plan.allocations}
        # argentina overweight, cash overweight (20 vs 10) -> must not receive.
        self.assertNotIn("argentina_equity", buckets)
        self.assertNotIn("cash_or_short_term_yield", buckets)
        # All kept allocations respect min_trade_usd.
        min_trade = float(self.policy.constraints["min_trade_usd"])
        for a in plan.allocations:
            self.assertGreaterEqual(a.allocation_usd + 1e-9, min_trade)

    def test_zero_contribution_returns_empty_plan(self) -> None:
        plan = build_contribution_allocation_plan(0.0, self.assets, self.policy)
        self.assertEqual(plan.allocations, tuple())
        self.assertEqual(plan.skipped_allocations, tuple())
        self.assertEqual(plan.unallocated_usd, 0.0)
        self.assertEqual(plan.warnings, tuple())


if __name__ == "__main__":
    unittest.main()
