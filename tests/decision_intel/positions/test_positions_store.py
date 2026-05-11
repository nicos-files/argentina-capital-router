import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.decision_intel.positions.positions_store import load_positions_snapshot


class PositionsStoreTests(unittest.TestCase):
    def test_load_positions_snapshot_cash_and_fx(self) -> None:
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            positions_path = base / "data" / "results" / "positions.json"
            positions_path.parent.mkdir(parents=True, exist_ok=True)
            positions_path.write_text(
                json.dumps(
                    {
                        "positions": [
                            {
                                "asset_id": "AAPL",
                                "broker": "iol",
                                "qty": 2.0,
                                "avg_price": 150.0,
                                "currency": "USD",
                                "fx_rate_used": 1.0,
                                "fx_rate_source": "native_usd",
                            }
                        ],
                        "cash": {"USD": 100.0},
                        "cash_by_broker": {"iol": {"USD": 100.0}},
                    }
                ),
                encoding="utf-8",
            )

            snapshot = load_positions_snapshot(base)
            self.assertEqual(snapshot.cash_by_currency.get("USD"), 100.0)
            self.assertEqual(snapshot.cash_by_broker["iol"]["USD"], 100.0)
            position = snapshot.positions["AAPL"]
            self.assertEqual(position.fx_rate_used, 1.0)
            self.assertEqual(position.fx_rate_source, "native_usd")


if __name__ == "__main__":
    unittest.main()
