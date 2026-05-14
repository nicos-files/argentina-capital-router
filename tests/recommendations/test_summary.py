"""Tests for src/recommendations/summary.py.

Manual review only. No network. No broker automation.
"""
from __future__ import annotations

import unittest

from src.recommendations.models import DailyCapitalPlan
from src.recommendations.summary import (
    NOT_AN_ORDER_NOTE,
    SCHEMA_VERSION,
    build_daily_recommendation_summary,
    is_empty_portfolio,
)


def _make_plan(
    *,
    portfolio_snapshot_id=None,
    portfolio_total_value_usd=None,
    portfolio_source="manual",
    positions_loaded=0,
    cash_balances_loaded=0,
    allocations=(),
    skipped=(),
    warnings=(),
    data_warnings=(),
    allocation_warnings=(),
    portfolio_warnings=(),
    decision="INVEST_DIRECT_LONG_TERM",
    rationale="route to long-term",
    market_snapshot_id="manual-example-2026-05-12",
    market_completeness="complete",
    constraints=None,
    target_bucket_weights=None,
) -> DailyCapitalPlan:
    metadata: dict = {
        "policy_id": "default",
        "long_term_policy_id": "long_term_default",
        "tactical_capital_available_usd": 0.0,
        "universe_size": 10,
        "opportunity_simulated": False,
        "opportunity_from_snapshot": False,
        "constraints": constraints
        or {
            "min_trade_usd": 10.0,
            "max_allocations_per_contribution": 5,
        },
    }
    if market_snapshot_id is not None:
        metadata["market_snapshot"] = {
            "snapshot_id": market_snapshot_id,
            "as_of": "2026-05-12",
            "source": "manual",
            "completeness": market_completeness,
            "summary": {},
        }
    if portfolio_snapshot_id is not None:
        metadata["portfolio_snapshot"] = {
            "snapshot_id": portfolio_snapshot_id,
            "as_of": "2026-05-12",
            "source": portfolio_source,
            "completeness": "complete",
            "summary": {
                "positions_loaded": positions_loaded,
                "cash_balances_loaded": cash_balances_loaded,
            },
            "target_bucket_weights": target_bucket_weights
            or {
                "core_global_equity": 50.0,
                "cedears_single_names": 30.0,
                "argentina_equity": 10.0,
                "cash_or_short_term_yield": 10.0,
            },
        }
    return DailyCapitalPlan(
        as_of="2026-05-12",
        manual_review_only=True,
        live_trading_enabled=False,
        monthly_long_term_contribution_usd=200.0,
        routing_decision={
            "decision": decision,
            "rationale": rationale,
            "long_term_capital_allocated_usd": 200.0,
            "tactical_capital_allocated_usd": 0.0,
            "opportunity_id": None,
            "warnings": list(warnings),
        },
        long_term_allocations=tuple(allocations),
        warnings=tuple(warnings),
        metadata=metadata,
        market_snapshot_id=market_snapshot_id,
        prices_used=tuple(),
        fx_rates_used=tuple(),
        rate_inputs_used=tuple(),
        data_warnings=tuple(data_warnings),
        portfolio_snapshot_id=portfolio_snapshot_id,
        portfolio_total_value_usd=portfolio_total_value_usd,
        current_bucket_weights={},
        portfolio_warnings=tuple(portfolio_warnings),
        skipped_allocations=tuple(skipped),
        unallocated_usd=0.0,
        allocation_warnings=tuple(allocation_warnings),
    )


class IsEmptyPortfolioTests(unittest.TestCase):
    def test_no_portfolio_at_all_is_empty(self) -> None:
        plan = _make_plan(portfolio_snapshot_id=None)
        self.assertTrue(is_empty_portfolio(plan))

    def test_generated_empty_source_is_empty(self) -> None:
        plan = _make_plan(
            portfolio_snapshot_id="empty-portfolio-2026-05-12",
            portfolio_source="generated_empty",
            positions_loaded=0,
            cash_balances_loaded=0,
        )
        self.assertTrue(is_empty_portfolio(plan))

    def test_zero_positions_and_cash_is_empty(self) -> None:
        plan = _make_plan(
            portfolio_snapshot_id="manual-portfolio-2026-05-12",
            portfolio_source="manual",
            positions_loaded=0,
            cash_balances_loaded=0,
        )
        self.assertTrue(is_empty_portfolio(plan))

    def test_populated_portfolio_is_not_empty(self) -> None:
        plan = _make_plan(
            portfolio_snapshot_id="manual-portfolio-2026-05-12",
            portfolio_source="manual",
            positions_loaded=3,
            cash_balances_loaded=1,
        )
        self.assertFalse(is_empty_portfolio(plan))


class BuildDailyRecommendationSummaryTests(unittest.TestCase):
    def test_required_safety_flags_present_and_correct(self) -> None:
        plan = _make_plan(portfolio_snapshot_id=None)
        summary = build_daily_recommendation_summary(plan)
        self.assertEqual(summary["schema_version"], SCHEMA_VERSION)
        self.assertIs(summary["manual_review_only"], True)
        self.assertIs(summary["live_trading_enabled"], False)
        self.assertIs(summary["no_orders"], True)
        self.assertIn("not orders", summary["note"].lower())
        self.assertEqual(summary["note"], NOT_AN_ORDER_NOTE)

    def test_core_fields_round_trip(self) -> None:
        allocations = [
            {
                "symbol": "SPY",
                "asset_class": "cedear",
                "bucket": "core_global_equity",
                "allocation_usd": 125.0,
                "rationale": "policy target",
            },
            {
                "symbol": "AAPL",
                "asset_class": "cedear",
                "bucket": "cedears_single_names",
                "allocation_usd": 16.67,
                "rationale": "policy target",
            },
        ]
        plan = _make_plan(
            portfolio_snapshot_id="empty-portfolio-2026-05-12",
            portfolio_source="generated_empty",
            portfolio_total_value_usd=0.0,
            allocations=allocations,
        )
        summary = build_daily_recommendation_summary(
            plan, generated_files=["capital_routing/x.json"]
        )
        self.assertEqual(summary["date"], "2026-05-12")
        self.assertEqual(summary["recommendation_type"], "INVEST_DIRECT_LONG_TERM")
        self.assertEqual(summary["monthly_contribution_usd"], 200.0)
        self.assertIs(summary["is_empty_portfolio"], True)
        self.assertEqual(summary["portfolio_total_value_usd"], 0.0)
        self.assertEqual(len(summary["recommended_allocations"]), 2)
        self.assertEqual(summary["recommended_allocations"][0]["symbol"], "SPY")
        self.assertEqual(
            summary["generated_files"], ["capital_routing/x.json"]
        )
        # Data quality block carries the snapshot completeness.
        dq = summary["data_quality"]
        self.assertEqual(
            dq["market_snapshot"]["completeness"], "complete"
        )
        self.assertEqual(
            dq["portfolio_snapshot"]["source"], "generated_empty"
        )

    def test_skipped_allocations_compact(self) -> None:
        plan = _make_plan(
            portfolio_snapshot_id=None,
            skipped=[
                {
                    "symbol": "COME",
                    "bucket": "argentina_equity",
                    "suggested_usd": 4.0,
                    "reason": "below min_trade_usd",
                    "extra": "ignored",
                }
            ],
        )
        summary = build_daily_recommendation_summary(plan)
        self.assertEqual(len(summary["skipped_allocations"]), 1)
        skipped = summary["skipped_allocations"][0]
        self.assertEqual(skipped["symbol"], "COME")
        self.assertEqual(skipped["suggested_usd"], 4.0)
        self.assertIn("min_trade_usd", skipped["reason"])
        self.assertNotIn("extra", skipped)  # compact schema only

    def test_warnings_deduplicated_and_combined(self) -> None:
        plan = _make_plan(
            portfolio_snapshot_id=None,
            warnings=["dup", "alpha"],
            data_warnings=["dup", "beta"],
        )
        summary = build_daily_recommendation_summary(plan)
        self.assertEqual(summary["warnings"], ["dup", "alpha", "beta"])

    def test_constraints_surface_through(self) -> None:
        plan = _make_plan(
            portfolio_snapshot_id=None,
            constraints={
                "min_trade_usd": 25.0,
                "max_allocations_per_contribution": 7,
            },
        )
        summary = build_daily_recommendation_summary(plan)
        self.assertEqual(summary["constraints"]["min_trade_usd"], 25.0)
        self.assertEqual(
            summary["constraints"]["max_allocations_per_contribution"], 7
        )

    def test_no_forbidden_keys(self) -> None:
        plan = _make_plan(portfolio_snapshot_id=None)
        summary = build_daily_recommendation_summary(plan)
        forbidden = (
            "execution_plan",
            "final_decision",
            "order",
            "broker",
            "api_key",
            "apikey",
        )
        import json

        blob = json.dumps(summary).lower()
        for token in forbidden:
            # Allow the substring 'order' inside 'no_orders' / 'orders'
            # disclaimer; assert it never surfaces as its own JSON key.
            self.assertNotIn(f'"{token}"', blob)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
