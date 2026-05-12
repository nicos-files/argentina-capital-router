import json
import tempfile
import unittest
from pathlib import Path

from src.market_data.manual_snapshot import load_manual_market_snapshot
from src.opportunities.carry_trade import (
    ATTRACTIVE,
    AVOID,
    CarryInputs,
    WEAK,
    build_carry_inputs_from_snapshot,
    score_carry_opportunity,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_SNAPSHOT = (
    REPO_ROOT / "config" / "data_inputs" / "manual_market_snapshot.example.json"
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


class BuildCarryInputsFromSnapshotTests(unittest.TestCase):
    def test_builds_expected_inputs(self) -> None:
        snapshot = load_manual_market_snapshot(EXAMPLE_SNAPSHOT)
        inputs = build_carry_inputs_from_snapshot(
            snapshot,
            estimated_cost_pct=0.3,
            duration_days=8,
            fx_risk_score=55.0,
            liquidity_risk_score=45.0,
        )
        # Values come from the example snapshot file.
        self.assertEqual(inputs.expected_monthly_rate_pct, 2.5)
        self.assertEqual(inputs.expected_fx_devaluation_pct, 1.5)
        self.assertEqual(inputs.estimated_cost_pct, 0.3)
        self.assertEqual(inputs.duration_days, 8)
        self.assertEqual(inputs.fx_risk_score, 55.0)
        self.assertEqual(inputs.liquidity_risk_score, 45.0)
        self.assertIn("snapshot", inputs.notes.lower())

    def test_custom_keys(self) -> None:
        snapshot = load_manual_market_snapshot(EXAMPLE_SNAPSHOT)
        inputs = build_carry_inputs_from_snapshot(
            snapshot,
            rate_key="caucion_monthly_pct",
        )
        self.assertEqual(inputs.expected_monthly_rate_pct, 2.8)

    def test_missing_rate_key_raises(self) -> None:
        snapshot = load_manual_market_snapshot(EXAMPLE_SNAPSHOT)
        with self.assertRaises(ValueError) as ctx:
            build_carry_inputs_from_snapshot(snapshot, rate_key="nonexistent_rate")
        self.assertIn("nonexistent_rate", str(ctx.exception))

    def test_missing_expected_fx_key_raises(self) -> None:
        snapshot = load_manual_market_snapshot(EXAMPLE_SNAPSHOT)
        with self.assertRaises(ValueError) as ctx:
            build_carry_inputs_from_snapshot(
                snapshot, expected_fx_key="nonexistent_fx"
            )
        self.assertIn("nonexistent_fx", str(ctx.exception))

    def test_score_carry_still_works_on_snapshot_inputs(self) -> None:
        snapshot = load_manual_market_snapshot(EXAMPLE_SNAPSHOT)
        inputs = build_carry_inputs_from_snapshot(snapshot)
        score = score_carry_opportunity(inputs)
        self.assertGreaterEqual(score.score, 0.0)
        self.assertLessEqual(score.score, 100.0)


if __name__ == "__main__":
    unittest.main()
