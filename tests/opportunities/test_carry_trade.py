import unittest

from src.opportunities.carry_trade import (
    ATTRACTIVE,
    AVOID,
    CarryInputs,
    WEAK,
    score_carry_opportunity,
)


class CarryTradeTests(unittest.TestCase):
    def test_attractive_scenario(self) -> None:
        inputs = CarryInputs(
            opportunity_id="opp-att",
            expected_monthly_rate_pct=8.0,
            expected_fx_devaluation_pct=2.0,
            estimated_cost_pct=0.5,
            duration_days=7,
            fx_risk_score=30.0,
            liquidity_risk_score=30.0,
        )
        score = score_carry_opportunity(inputs)
        self.assertGreater(score.expected_net_return_pct, 0)
        self.assertGreaterEqual(score.score, 75)
        self.assertEqual(score.classification, ATTRACTIVE)

    def test_weak_or_avoid_scenario(self) -> None:
        inputs = CarryInputs(
            opportunity_id="opp-weak",
            expected_monthly_rate_pct=2.0,
            expected_fx_devaluation_pct=1.8,
            estimated_cost_pct=0.1,
            duration_days=15,
            fx_risk_score=60.0,
            liquidity_risk_score=60.0,
        )
        score = score_carry_opportunity(inputs)
        self.assertIn(score.classification, (WEAK, AVOID, "MODERATE"))
        self.assertLess(score.score, 75)

    def test_negative_expected_net_return_warning(self) -> None:
        inputs = CarryInputs(
            opportunity_id="opp-neg",
            expected_monthly_rate_pct=2.0,
            expected_fx_devaluation_pct=5.0,
            estimated_cost_pct=0.5,
            duration_days=7,
            fx_risk_score=30.0,
            liquidity_risk_score=30.0,
        )
        score = score_carry_opportunity(inputs)
        self.assertLess(score.expected_net_return_pct, 0)
        self.assertTrue(
            any("non-positive expected net return" in w for w in score.warnings)
        )
        self.assertNotEqual(score.classification, ATTRACTIVE)

    def test_high_risk_warnings(self) -> None:
        inputs = CarryInputs(
            opportunity_id="opp-risk",
            expected_monthly_rate_pct=10.0,
            expected_fx_devaluation_pct=2.0,
            estimated_cost_pct=0.5,
            duration_days=7,
            fx_risk_score=90.0,
            liquidity_risk_score=85.0,
        )
        score = score_carry_opportunity(inputs)
        self.assertTrue(any("high FX risk" in w for w in score.warnings))
        self.assertTrue(any("high liquidity risk" in w for w in score.warnings))


if __name__ == "__main__":
    unittest.main()
