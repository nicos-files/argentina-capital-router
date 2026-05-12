import unittest

from src.capital_allocation.buckets import build_default_capital_state
from src.capital_allocation.capital_router import (
    DO_NOT_USE_CONTRIBUTION_FOR_TACTICAL,
    INVEST_DIRECT_LONG_TERM,
    TACTICAL_THEN_LONG_TERM,
    TacticalOpportunity,
    route_capital,
)
from src.capital_allocation.contribution_policy import load_contribution_policy


class CapitalRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_contribution_policy()
        self.capital_state = build_default_capital_state(
            monthly_contribution_usd=200, tactical_capital_available_usd=0
        )

    def _good_opportunity(self, **overrides) -> TacticalOpportunity:
        defaults = dict(
            opportunity_id="opp-1",
            opportunity_type="carry_trade",
            expected_net_return_pct=3.0,
            score=85.0,
            duration_days=7,
            fx_risk_score=30.0,
            liquidity_risk_score=30.0,
            uses_leverage=False,
            has_clear_exit_date=True,
        )
        defaults.update(overrides)
        return TacticalOpportunity(**defaults)

    def test_no_opportunity_invests_long_term(self) -> None:
        decision = route_capital(self.policy, self.capital_state, opportunity=None)
        self.assertEqual(decision.decision, INVEST_DIRECT_LONG_TERM)
        self.assertEqual(decision.long_term_capital_allocated_usd, 200)
        self.assertTrue(decision.long_term_contribution_protected)
        self.assertFalse(decision.live_trading_enabled)
        self.assertTrue(decision.manual_review_only)

    def test_blocked_opportunity_type(self) -> None:
        opp = self._good_opportunity(opportunity_type="leveraged_trade")
        decision = route_capital(self.policy, self.capital_state, opportunity=opp)
        self.assertEqual(decision.decision, DO_NOT_USE_CONTRIBUTION_FOR_TACTICAL)
        self.assertEqual(decision.long_term_capital_allocated_usd, 200)

    def test_leverage_blocks_routing(self) -> None:
        opp = self._good_opportunity(uses_leverage=True)
        decision = route_capital(self.policy, self.capital_state, opportunity=opp)
        self.assertEqual(decision.decision, DO_NOT_USE_CONTRIBUTION_FOR_TACTICAL)

    def test_no_clear_exit_blocks_routing(self) -> None:
        opp = self._good_opportunity(has_clear_exit_date=False)
        decision = route_capital(self.policy, self.capital_state, opportunity=opp)
        self.assertEqual(decision.decision, DO_NOT_USE_CONTRIBUTION_FOR_TACTICAL)

    def test_low_score_routes_to_long_term(self) -> None:
        opp = self._good_opportunity(score=10.0)
        decision = route_capital(self.policy, self.capital_state, opportunity=opp)
        self.assertEqual(decision.decision, INVEST_DIRECT_LONG_TERM)

    def test_valid_opportunity_routes_to_tactical(self) -> None:
        opp = self._good_opportunity()
        decision = route_capital(self.policy, self.capital_state, opportunity=opp)
        self.assertEqual(decision.decision, TACTICAL_THEN_LONG_TERM)
        self.assertTrue(decision.long_term_contribution_protected)
        self.assertTrue(decision.manual_review_only)
        self.assertFalse(decision.live_trading_enabled)

    def test_long_term_contribution_protected_flag_is_always_true(self) -> None:
        # Across multiple routing decisions, the long-term contribution must remain
        # conceptually protected (loss absorption order keeps it safe in policy).
        opps = [
            None,
            self._good_opportunity(),
            self._good_opportunity(uses_leverage=True),
            self._good_opportunity(score=5.0),
        ]
        for opp in opps:
            decision = route_capital(self.policy, self.capital_state, opportunity=opp)
            self.assertTrue(decision.long_term_contribution_protected)


if __name__ == "__main__":
    unittest.main()
