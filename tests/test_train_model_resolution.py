import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.pipeline.train_model import _load_training_dataset, resolve_features_path, select_relevant_features


class TrainModelResolutionTests(unittest.TestCase):
    def test_resolve_features_path_prefers_latest_with_target_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            old_path = base / "2026" / "04" / "16" / "features.parquet"
            new_path = base / "2026" / "04" / "21" / "features.parquet"
            old_path.parent.mkdir(parents=True, exist_ok=True)
            new_path.parent.mkdir(parents=True, exist_ok=True)

            pd.DataFrame(
                {
                    "ticker": ["AAA"] * 60,
                    "target_regresion_t+5": [0.01] * 60,
                }
            ).to_parquet(old_path, index=False)
            pd.DataFrame(
                {
                    "ticker": ["AAA"] * 10,
                    "target_regresion_t+5": [0.01] * 10,
                }
            ).to_parquet(new_path, index=False)

            date, path = resolve_features_path(
                "2026-04-22",
                required_targets=["target_regresion_t+5"],
                min_target_rows=50,
                base_path=base,
            )

            self.assertEqual(date, datetime(2026, 4, 16))
            self.assertEqual(path, old_path)

    def test_resolve_features_path_uses_latest_when_no_target_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            old_path = base / "2026" / "04" / "16" / "features.parquet"
            new_path = base / "2026" / "04" / "21" / "features.parquet"
            old_path.parent.mkdir(parents=True, exist_ok=True)
            new_path.parent.mkdir(parents=True, exist_ok=True)

            pd.DataFrame({"ticker": ["AAA"], "x": [1]}).to_parquet(old_path, index=False)
            pd.DataFrame({"ticker": ["BBB"], "x": [2]}).to_parquet(new_path, index=False)

            date, path = resolve_features_path("2026-04-22", base_path=base)

            self.assertEqual(date, datetime(2026, 4, 21))
            self.assertEqual(path, new_path)

    def test_load_training_dataset_concatenates_historical_files_for_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            p1 = base / "2026" / "04" / "18" / "features.parquet"
            p2 = base / "2026" / "04" / "19" / "features.parquet"
            p1.parent.mkdir(parents=True, exist_ok=True)
            p2.parent.mkdir(parents=True, exist_ok=True)

            pd.DataFrame(
                {
                    "ticker": ["AAA", "BBB"],
                    "feature": [1.0, 2.0],
                    "target_regresion_t+1": [0.01, -0.01],
                }
            ).to_parquet(p1, index=False)
            pd.DataFrame(
                {
                    "ticker": ["CCC", "DDD"],
                    "feature": [3.0, 4.0],
                    "target_regresion_t+1": [0.02, -0.02],
                }
            ).to_parquet(p2, index=False)

            date, path, dataset, files_used = _load_training_dataset(
                requested_date="2026-04-22",
                target_col="target_regresion_t+1",
                lookback_days=10,
                base_path=base,
            )

            self.assertEqual(date, datetime(2026, 4, 19))
            self.assertEqual(path, p2)
            self.assertEqual(files_used, 2)
            self.assertEqual(len(dataset), 4)

    def test_select_relevant_features_handles_nullable_numeric_na(self) -> None:
        df = pd.DataFrame(
            {
                "feature_ok": [1.0, 2.0, 3.0],
                "feature_all_na": pd.Series([pd.NA, pd.NA, pd.NA], dtype="Float64"),
                "target": [0, 1, 0],
            }
        )

        selected = select_relevant_features(df, "target")

        self.assertEqual(selected, ["feature_ok"])


if __name__ == "__main__":
    unittest.main()
