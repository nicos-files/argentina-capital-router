import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.tools.run_all import _build_intraday_candidates, _build_long_term_candidates


class _FakeBooster:
    feature_names = ["feature_a"]


class _FakeModel:
    def get_booster(self):
        return _FakeBooster()

    def predict_proba(self, X):
        probs = X["feature_a"].astype(float).to_numpy()
        return np.column_stack([1.0 - probs, probs])


class _FakeRegModel:
    def get_booster(self):
        return _FakeBooster()

    def predict(self, X):
        return X["feature_a"].astype(float).to_numpy()


class RunAllDecisionFilterTests(unittest.TestCase):
    def test_build_intraday_candidates_keeps_only_positive_empirical_edge(self) -> None:
        model = _FakeModel()
        current_df = pd.DataFrame(
            [
                {"ticker": "AAA", "feature_a": 0.90, "date": "2026-04-21"},
                {"ticker": "BBB", "feature_a": 0.92, "date": "2026-04-21"},
            ]
        )
        history_rows = []
        for _ in range(30):
            history_rows.append(
                {"ticker": "AAA", "feature_a": 0.90, "date": "2026-03-01", "target_regresion_t+1": 0.012}
            )
            history_rows.append(
                {"ticker": "BBB", "feature_a": 0.92, "date": "2026-03-01", "target_regresion_t+1": -0.010}
            )
        history_df = pd.DataFrame(history_rows)

        items = _build_intraday_candidates(
            current_df=current_df,
            history_df=history_df,
            model=model,
            asof_date="2026-04-21",
            top_k=10,
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["ticker"], "AAA")
        self.assertGreater(items[0]["expected_return_gross_pct"], 0.003)

    def test_build_intraday_candidates_applies_oos_trade_filter(self) -> None:
        model = _FakeModel()
        current_df = pd.DataFrame(
            [
                {"ticker": "AAA", "feature_a": 0.90, "date": "2026-04-21"},
                {"ticker": "BBB", "feature_a": 0.91, "date": "2026-04-21"},
            ]
        )
        history_rows = []
        for _ in range(30):
            history_rows.append(
                {"ticker": "AAA", "feature_a": 0.90, "date": "2026-03-01", "target_regresion_t+1": 0.012}
            )
            history_rows.append(
                {"ticker": "BBB", "feature_a": 0.91, "date": "2026-03-01", "target_regresion_t+1": 0.011}
            )
        history_df = pd.DataFrame(history_rows)
        oos_stats = {
            "AAA": {"rows": 20, "mean_ret_adj": 0.002, "hit_rate": 0.60},
            "BBB": {"rows": 20, "mean_ret_adj": 0.0001, "hit_rate": 0.60},
        }

        items = _build_intraday_candidates(
            current_df=current_df,
            history_df=history_df,
            model=model,
            asof_date="2026-04-21",
            top_k=10,
            oos_ticker_stats=oos_stats,
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["ticker"], "AAA")
        self.assertEqual(items[0]["oos_trade_count"], 20)

    def test_build_long_term_candidates_uses_regression_and_empirical_filter(self) -> None:
        import src.tools.run_all as module

        model = _FakeRegModel()
        current_df = pd.DataFrame(
            [
                {"ticker": "AAA", "feature_a": 0.03, "date": "2026-04-21"},
                {"ticker": "BBB", "feature_a": 0.04, "date": "2026-04-21"},
            ]
        )
        history_rows = []
        for _ in range(30):
            history_rows.append(
                {"ticker": "AAA", "feature_a": 0.03, "date": "2026-03-01", "target_regresion_t+5": 0.04}
            )
            history_rows.append(
                {"ticker": "BBB", "feature_a": 0.04, "date": "2026-03-01", "target_regresion_t+5": -0.03}
            )
        history_df = pd.DataFrame(history_rows)

        original = module.LONG_TERM_MODEL_PATH
        module.LONG_TERM_MODEL_PATH = Path(__file__)
        try:
            with patch("joblib.load", return_value=model):
                items = _build_long_term_candidates(
                    current_df=current_df,
                    history_df=history_df,
                    asof_date="2026-04-21",
                    top_k=10,
                )
        finally:
            module.LONG_TERM_MODEL_PATH = original

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["ticker"], "AAA")


if __name__ == "__main__":
    unittest.main()
