import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.backtest.oos_evaluation import split_oos_by_date
from src.backtest.prepare_data import prepare_data


class _FakeBooster:
    feature_names = ["feature_a"]


class _FakeModel:
    def get_booster(self):
        return _FakeBooster()

    def predict(self, X):
        return np.ones(len(X), dtype=int)

    def predict_proba(self, X):
        probs = np.full(len(X), 0.8, dtype=float)
        return np.column_stack([1.0 - probs, probs])


class OosEvaluationTests(unittest.TestCase):
    def test_split_oos_by_date_applies_purge_gap(self) -> None:
        rows = []
        for idx, day in enumerate(pd.date_range("2026-01-01", periods=100, freq="D")):
            rows.append({"date": day.strftime("%Y-%m-%d"), "ticker": "AAA", "value": idx})
        df = pd.DataFrame(rows)

        train_df, test_df, meta = split_oos_by_date(df, test_fraction=0.3, purge_days=1, min_train_days=60, min_test_days=20)

        self.assertLess(pd.to_datetime(train_df["date"]).max(), pd.to_datetime(test_df["date"]).min())
        self.assertEqual(meta["purge_days"], 1)
        self.assertEqual(meta["train_days"] + meta["test_days"] + meta["purge_days"], 100)

    def test_prepare_data_accepts_model_instance(self) -> None:
        df = pd.DataFrame(
            {
                "date": ["2026-04-20", "2026-04-21"],
                "ticker": ["AAA", "AAA"],
                "feature_a": [0.1, 0.2],
                "target_regresion_t+1": [0.01, 0.02],
                "target_clasificacion_t+1": [1, 1],
                "daily_return": [0.0, 0.0],
            }
        )

        prepared = prepare_data(
            features_path=df,
            model_path=_FakeModel(),
            clip_ret=0.05,
            stop_loss=0.03,
            take_profit=0.05,
        )

        self.assertIn("prediccion", prepared.columns)
        self.assertIn("proba", prepared.columns)
        self.assertEqual(len(prepared), 2)


if __name__ == "__main__":
    unittest.main()
