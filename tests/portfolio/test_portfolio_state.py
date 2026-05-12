import copy
import json
import tempfile
import unittest
from pathlib import Path

from src.portfolio.portfolio_state import (
    get_position_by_symbol,
    load_manual_portfolio_snapshot,
    summarize_portfolio_snapshot,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_PATH = (
    REPO_ROOT / "config" / "portfolio" / "manual_portfolio_snapshot.example.json"
)


def _payload() -> dict:
    return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))


def _write_tmp(payload: dict, tmp: Path) -> Path:
    p = tmp / "portfolio.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


class LoadPortfolioSnapshotTests(unittest.TestCase):
    def test_loads_example(self) -> None:
        snap = load_manual_portfolio_snapshot(EXAMPLE_PATH)
        self.assertTrue(snap.manual_review_only)
        self.assertFalse(snap.live_trading_enabled)
        self.assertEqual(snap.base_currency, "USD")
        self.assertEqual(snap.completeness, "partial")
        self.assertGreaterEqual(len(snap.positions), 3)
        symbols = {p.symbol for p in snap.positions}
        self.assertEqual(symbols, {"SPY", "AAPL", "GGAL"})
        self.assertGreaterEqual(len(snap.cash), 2)

    def test_symbol_normalized_on_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            payload = _payload()
            payload["positions"] = copy.deepcopy(payload["positions"])
            payload["positions"][0]["symbol"] = " ggal.ba "
            path = _write_tmp(payload, tmp)
            snap = load_manual_portfolio_snapshot(path)
            self.assertTrue(any(p.symbol == "GGAL" for p in snap.positions))

    def test_get_position_by_symbol(self) -> None:
        snap = load_manual_portfolio_snapshot(EXAMPLE_PATH)
        pos = get_position_by_symbol(snap, "spy")
        self.assertIsNotNone(pos)
        self.assertEqual(pos.symbol, "SPY")
        self.assertIsNone(get_position_by_symbol(snap, "NVDA"))

    def test_summarize(self) -> None:
        snap = load_manual_portfolio_snapshot(EXAMPLE_PATH)
        summary = summarize_portfolio_snapshot(snap)
        self.assertEqual(summary["positions_loaded"], len(snap.positions))
        self.assertEqual(summary["cash_balances_loaded"], len(snap.cash))
        self.assertEqual(summary["completeness"], "partial")


class InvalidSnapshotTests(unittest.TestCase):
    def test_live_trading_true_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            payload = _payload()
            payload["live_trading_enabled"] = True
            path = _write_tmp(payload, tmp)
            with self.assertRaises(ValueError):
                load_manual_portfolio_snapshot(path)

    def test_manual_review_false_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            payload = _payload()
            payload["manual_review_only"] = False
            path = _write_tmp(payload, tmp)
            with self.assertRaises(ValueError):
                load_manual_portfolio_snapshot(path)

    def test_zero_quantity_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            payload = _payload()
            payload["positions"] = copy.deepcopy(payload["positions"])
            payload["positions"][0]["quantity"] = 0
            path = _write_tmp(payload, tmp)
            with self.assertRaises(ValueError):
                load_manual_portfolio_snapshot(path)

    def test_negative_cash_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            payload = _payload()
            payload["cash"] = copy.deepcopy(payload["cash"])
            payload["cash"][0]["amount"] = -1.0
            path = _write_tmp(payload, tmp)
            with self.assertRaises(ValueError):
                load_manual_portfolio_snapshot(path)

    def test_missing_top_level_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            payload = _payload()
            payload.pop("base_currency")
            path = _write_tmp(payload, tmp)
            with self.assertRaises(ValueError):
                load_manual_portfolio_snapshot(path)

    def test_missing_file_raises(self) -> None:
        with self.assertRaises(ValueError):
            load_manual_portfolio_snapshot(Path("/nonexistent/portfolio.json"))


if __name__ == "__main__":
    unittest.main()
