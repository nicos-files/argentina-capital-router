import copy
import json
import tempfile
import unittest
from pathlib import Path

from src.portfolio.portfolio_state import (
    build_empty_portfolio_snapshot,
    get_position_by_symbol,
    load_manual_portfolio_snapshot,
    manual_portfolio_snapshot_to_dict,
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


class BuildEmptyPortfolioSnapshotTests(unittest.TestCase):
    def test_returns_complete_empty_portfolio(self) -> None:
        snap = build_empty_portfolio_snapshot("2026-05-12")
        self.assertEqual(snap.as_of, "2026-05-12")
        self.assertEqual(snap.snapshot_id, "empty-portfolio-2026-05-12")
        self.assertEqual(snap.source, "generated_empty")
        self.assertEqual(snap.base_currency, "USD")
        self.assertEqual(snap.completeness, "complete")
        self.assertEqual(snap.cash, tuple())
        self.assertEqual(snap.positions, tuple())
        self.assertEqual(snap.warnings, tuple())

    def test_manual_review_only_true_and_live_trading_false(self) -> None:
        snap = build_empty_portfolio_snapshot("2026-05-12")
        self.assertIs(snap.manual_review_only, True)
        self.assertIs(snap.live_trading_enabled, False)

    def test_custom_base_currency(self) -> None:
        snap = build_empty_portfolio_snapshot("2026-05-12", base_currency="eur")
        self.assertEqual(snap.base_currency, "EUR")

    def test_empty_base_currency_falls_back_to_usd(self) -> None:
        snap = build_empty_portfolio_snapshot("2026-05-12", base_currency="")
        self.assertEqual(snap.base_currency, "USD")

    def test_invalid_as_of_raises(self) -> None:
        with self.assertRaises(ValueError):
            build_empty_portfolio_snapshot("")
        with self.assertRaises(ValueError):
            build_empty_portfolio_snapshot("   ")

    def test_round_trip_via_serializer_loader(self) -> None:
        """Writing the empty snapshot and reloading it yields an equivalent
        snapshot that still passes the loader's hard checks."""
        snap = build_empty_portfolio_snapshot("2026-05-12")
        payload = manual_portfolio_snapshot_to_dict(snap)
        # The serialized payload must satisfy the loader's contract.
        self.assertTrue(payload["manual_review_only"])
        self.assertFalse(payload["live_trading_enabled"])
        self.assertEqual(payload["cash"], [])
        self.assertEqual(payload["positions"], [])

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "empty.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            reloaded = load_manual_portfolio_snapshot(path)
        self.assertEqual(reloaded.snapshot_id, snap.snapshot_id)
        self.assertEqual(reloaded.cash, tuple())
        self.assertEqual(reloaded.positions, tuple())
        self.assertEqual(reloaded.completeness, "complete")


if __name__ == "__main__":
    unittest.main()
