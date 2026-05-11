import sys
import unittest
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.tools.rebuild_features_history import _add_forward_targets


class RebuildFeaturesTargetsTests(unittest.TestCase):
    def test_add_forward_targets_builds_intraday_and_long_term(self) -> None:
        df = pd.DataFrame(
            {
                "ticker": ["AAA"] * 7,
                "date": pd.date_range("2026-01-01", periods=7, freq="D"),
                "open": [100, 101, 102, 103, 104, 105, 106],
                "close": [100, 101, 102, 103, 104, 105, 106],
                "daily_return": [0.0, 0.01, 0.0099, 0.0098, 0.0097, 0.0096, 0.0095],
            }
        )
        out = _add_forward_targets(df)
        first = out.iloc[0]
        self.assertAlmostEqual(float(first["target_regresion_t+1"]), 0.0, places=6)
        self.assertAlmostEqual(float(first["target_regresion_t+5"]), 4.0 / 101.0, places=6)
        self.assertEqual(int(first["target_clasificacion_t+1"]), 0)
        self.assertEqual(int(first["target_clasificacion_t+5"]), 1)


if __name__ == "__main__":
    unittest.main()
