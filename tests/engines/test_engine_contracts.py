import sys
import unittest
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.contracts.recommendations.recommendation_models import RecommendationOutput
from src.engines import (
    EngineContext,
    EngineDiagnostics,
    EngineResult,
    IntradayCryptoEngine,
    LongTermPortfolioEngine,
    StrategyEngine,
)


class EngineContractTests(unittest.TestCase):
    def test_engine_context_supports_minimal_construction(self) -> None:
        context = EngineContext(
            as_of=datetime(2026, 4, 21, 12, 0, 0),
            run_id="20260421-1200",
            mode="test",
            universe=[],
        )

        self.assertEqual(context.run_id, "20260421-1200")
        self.assertEqual(context.universe, [])
        self.assertEqual(context.config, {})

    def test_engine_diagnostics_defaults_are_sane(self) -> None:
        diagnostics = EngineDiagnostics(engine_name="demo")

        self.assertEqual(diagnostics.candidates_seen, 0)
        self.assertEqual(diagnostics.candidates_scored, 0)
        self.assertEqual(diagnostics.candidates_rejected, 0)
        self.assertEqual(diagnostics.warnings, [])
        self.assertEqual(diagnostics.metadata, {})

    def test_engine_result_holds_recommendation_output(self) -> None:
        output = RecommendationOutput.build(
            run_id="20260421-1200",
            horizon="LONG_TERM",
            asof_date="2026-04-21",
            policy_id="test",
            policy_version="1",
            constraints=[],
            sizing_rule="engine.boundary",
            recommendations=[],
            cash_summary={},
            cash_policy="engine.noop",
        )
        result = EngineResult(
            engine_name="demo",
            horizon="long_term",
            recommendations=output,
            diagnostics=EngineDiagnostics(engine_name="demo"),
        )

        self.assertIs(result.recommendations, output)

    def test_engine_can_return_valid_empty_output(self) -> None:
        engine = IntradayCryptoEngine()
        context = EngineContext(
            as_of=datetime(2026, 4, 21, 12, 0, 0),
            run_id="20260421-1200",
            mode="test",
            universe=[],
            metadata={"asof_date": "2026-04-21"},
        )

        result = engine.run(context)

        self.assertIsInstance(result.recommendations, RecommendationOutput)
        self.assertEqual(result.recommendations.to_payload()["recommendations"], [])

    def test_strategy_engine_protocol_matches_implementations(self) -> None:
        self.assertIsInstance(LongTermPortfolioEngine(), StrategyEngine)
        self.assertIsInstance(IntradayCryptoEngine(), StrategyEngine)


if __name__ == "__main__":
    unittest.main()
