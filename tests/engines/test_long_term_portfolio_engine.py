import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.contracts.recommendations.recommendation_models import RecommendationOutput
from src.engines import EngineContext, EngineDiagnostics, EngineResult, LongTermPortfolioEngine
from src.tools.run_all import _build_long_term_candidates


class _FakeBooster:
    feature_names = ["feature_a"]


class _FakeRegModel:
    def get_booster(self):
        return _FakeBooster()

    def predict(self, X):
        return X["feature_a"].astype(float).to_numpy()


class LongTermPortfolioEngineTests(unittest.TestCase):
    def test_engine_identity(self) -> None:
        engine = LongTermPortfolioEngine()
        self.assertEqual(engine.name, "long_term_portfolio")
        self.assertEqual(engine.horizon, "long_term")

    def test_run_returns_engine_result_contract(self) -> None:
        engine = LongTermPortfolioEngine()
        context = EngineContext(
            as_of=datetime(2026, 4, 21, 12, 0, 0),
            run_id="20260421-1200",
            mode="test",
            universe=[],
        )

        result = engine.run(context)

        self.assertIsInstance(result, EngineResult)
        self.assertIsInstance(result.recommendations, RecommendationOutput)
        self.assertIsInstance(result.diagnostics, EngineDiagnostics)

    def test_empty_universe_is_safe(self) -> None:
        engine = LongTermPortfolioEngine()
        context = EngineContext(
            as_of=datetime(2026, 4, 21, 12, 0, 0),
            run_id="20260421-1200",
            mode="test",
            universe=[],
            prices=pd.DataFrame(),
            metadata={"asof_date": "2026-04-21"},
        )

        result = engine.run(context)

        self.assertEqual(result.recommendations.to_payload()["recommendations"], [])
        self.assertTrue(any("Empty universe" in warning for warning in result.diagnostics.warnings))

    def test_missing_optional_data_does_not_crash(self) -> None:
        engine = LongTermPortfolioEngine()
        context = EngineContext(
            as_of=datetime(2026, 4, 21, 12, 0, 0),
            run_id="20260421-1200",
            mode="test",
            universe=["AAA"],
            prices=pd.DataFrame([{"ticker": "AAA", "feature_a": 0.03}]),
            metadata={"asof_date": "2026-04-21"},
        )

        result = engine.run(context)

        self.assertIsInstance(result, EngineResult)
        self.assertTrue(any("History frame missing or empty" in warning for warning in result.diagnostics.warnings))

    def test_engine_wraps_existing_long_term_logic(self) -> None:
        import src.tools.run_all as module

        engine = LongTermPortfolioEngine()
        model = _FakeRegModel()
        current_df = pd.DataFrame(
            [
                {"ticker": "AAA", "feature_a": 0.03, "date": "2026-04-21"},
                {"ticker": "BBB", "feature_a": 0.04, "date": "2026-04-21"},
            ]
        )
        history_df = pd.DataFrame(
            [
                {"ticker": "AAA", "feature_a": 0.03, "date": "2026-03-01", "target_regresion_t+5": 0.04}
                for _ in range(30)
            ]
            + [
                {"ticker": "BBB", "feature_a": 0.04, "date": "2026-03-01", "target_regresion_t+5": -0.03}
                for _ in range(30)
            ]
        )
        context = EngineContext(
            as_of=datetime(2026, 4, 21, 12, 0, 0),
            run_id="20260421-1200",
            mode="test",
            universe=["AAA", "BBB"],
            prices=current_df,
            metadata={"asof_date": "2026-04-21", "history_df": history_df, "top_k": 10},
        )

        original = module.LONG_TERM_MODEL_PATH
        module.LONG_TERM_MODEL_PATH = Path(__file__)
        try:
            with patch("joblib.load", return_value=model):
                direct = _build_long_term_candidates(
                    current_df=current_df,
                    history_df=history_df,
                    asof_date="2026-04-21",
                    top_k=10,
                )
                result = engine.run(context)
        finally:
            module.LONG_TERM_MODEL_PATH = original

        self.assertEqual(result.diagnostics.metadata["decision_rows"], direct)
        self.assertEqual([item["ticker"] for item in direct], ["AAA"])


if __name__ == "__main__":
    unittest.main()
