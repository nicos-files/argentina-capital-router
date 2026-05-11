import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.execution.crypto_paper_history import (
    build_crypto_paper_equity_curve,
    build_crypto_paper_history_report,
    build_crypto_paper_history_summary,
    build_crypto_paper_symbol_attribution,
    load_crypto_paper_daily_close_entry,
    load_crypto_paper_history,
    update_crypto_paper_history,
    upsert_crypto_paper_history,
)


class CryptoPaperHistoryTests(unittest.TestCase):
    def _write_daily_close(
        self,
        root: Path,
        *,
        as_of: str,
        starting_equity: float,
        ending_equity: float,
        total_pnl: float,
        total_return_pct: float,
        fees_paid: float,
        fills_count: int,
        rejected_orders_count: int,
        positions: list[dict] | None = None,
    ) -> None:
        root.mkdir(parents=True, exist_ok=True)
        payload = {
            "as_of": as_of,
            "positions_marked": positions or [],
            "warnings": [],
            "provider_health": {},
            "paper_only": True,
            "live_trading": False,
            "metadata": {"source_artifacts": []},
            "performance": {
                "as_of": as_of,
                "starting_cash": starting_equity,
                "ending_cash": ending_equity - sum((float(item.get("last_price") or item.get("avg_entry_price") or 0.0) * float(item.get("quantity") or 0.0)) for item in (positions or [])),
                "starting_equity": starting_equity,
                "ending_equity": ending_equity,
                "positions_value": sum((float(item.get("last_price") or item.get("avg_entry_price") or 0.0) * float(item.get("quantity") or 0.0)) for item in (positions or [])),
                "realized_pnl": 0.0,
                "unrealized_pnl": sum(float(item.get("unrealized_pnl") or 0.0) for item in (positions or [])),
                "total_pnl": total_pnl,
                "total_return_pct": total_return_pct,
                "fees_paid": fees_paid,
                "fills_count": fills_count,
                "accepted_orders_count": fills_count,
                "rejected_orders_count": rejected_orders_count,
                "open_positions_count": len(positions or []),
                "symbols_held": sorted({str(item.get("symbol")) for item in (positions or []) if item.get("symbol")}),
                "data_quality_warnings": [],
                "provider_health": {},
                "metadata": {},
                "paper_only": True,
                "live_trading": False,
            },
        }
        (root / "crypto_paper_daily_close.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        (root / "crypto_paper_performance_summary.json").write_text(json.dumps(payload["performance"], ensure_ascii=False), encoding="utf-8")

    def test_empty_history_plus_one_daily_close_creates_one_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            daily = Path(tmp) / "daily_close"
            history = Path(tmp) / "history"
            self._write_daily_close(
                daily,
                as_of="2026-04-24T19:00:00",
                starting_equity=100.0,
                ending_equity=101.0,
                total_pnl=1.0,
                total_return_pct=0.01,
                fees_paid=0.1,
                fills_count=1,
                rejected_orders_count=0,
            )
            entries, points, summary, _, _, _ = update_crypto_paper_history(daily_close_dir=daily, history_dir=history)
            self.assertEqual(len(entries), 1)
            self.assertEqual(len(points), 1)
            self.assertEqual(summary.days_count, 1)

    def test_existing_history_plus_new_daily_close_appends_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            daily = Path(tmp) / "daily_close"
            history = Path(tmp) / "history"
            self._write_daily_close(daily, as_of="2026-04-24T19:00:00", starting_equity=100.0, ending_equity=101.0, total_pnl=1.0, total_return_pct=0.01, fees_paid=0.1, fills_count=1, rejected_orders_count=0)
            update_crypto_paper_history(daily_close_dir=daily, history_dir=history)
            self._write_daily_close(daily, as_of="2026-04-25T19:00:00", starting_equity=101.0, ending_equity=99.0, total_pnl=-2.0, total_return_pct=-0.0198019802, fees_paid=0.1, fills_count=1, rejected_orders_count=1)
            entries, _, summary, _, _, _ = update_crypto_paper_history(daily_close_dir=daily, history_dir=history)
            self.assertEqual(len(entries), 2)
            self.assertEqual(summary.days_count, 2)

    def test_same_date_asof_replaces_existing_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            daily = Path(tmp) / "daily_close"
            history = Path(tmp) / "history"
            self._write_daily_close(daily, as_of="2026-04-24T19:00:00", starting_equity=100.0, ending_equity=101.0, total_pnl=1.0, total_return_pct=0.01, fees_paid=0.1, fills_count=1, rejected_orders_count=0)
            update_crypto_paper_history(daily_close_dir=daily, history_dir=history)
            self._write_daily_close(daily, as_of="2026-04-24T19:00:00", starting_equity=100.0, ending_equity=103.0, total_pnl=3.0, total_return_pct=0.03, fees_paid=0.2, fills_count=2, rejected_orders_count=0)
            entries, _, _, _, _, _ = update_crypto_paper_history(daily_close_dir=daily, history_dir=history)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].ending_equity, 103.0)

    def test_entries_are_sorted_chronologically(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            daily = Path(tmp) / "daily_close"
            history = Path(tmp) / "history"
            self._write_daily_close(daily, as_of="2026-04-25T19:00:00", starting_equity=100.0, ending_equity=99.0, total_pnl=-1.0, total_return_pct=-0.01, fees_paid=0.1, fills_count=1, rejected_orders_count=0)
            update_crypto_paper_history(daily_close_dir=daily, history_dir=history)
            self._write_daily_close(daily, as_of="2026-04-24T19:00:00", starting_equity=100.0, ending_equity=101.0, total_pnl=1.0, total_return_pct=0.01, fees_paid=0.1, fills_count=1, rejected_orders_count=0)
            entries, _, _, _, _, _ = update_crypto_paper_history(daily_close_dir=daily, history_dir=history)
            self.assertEqual([entry.date for entry in entries], ["2026-04-24", "2026-04-25"])

    def test_equity_curve_is_calculated_correctly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            daily = Path(tmp) / "daily_close"
            history = Path(tmp) / "history"
            self._write_daily_close(daily, as_of="2026-04-24T19:00:00", starting_equity=100.0, ending_equity=110.0, total_pnl=10.0, total_return_pct=0.1, fees_paid=0.1, fills_count=1, rejected_orders_count=0)
            update_crypto_paper_history(daily_close_dir=daily, history_dir=history)
            self._write_daily_close(daily, as_of="2026-04-25T19:00:00", starting_equity=110.0, ending_equity=121.0, total_pnl=11.0, total_return_pct=0.1, fees_paid=0.1, fills_count=1, rejected_orders_count=0)
            entries, points, _, _, _, _ = update_crypto_paper_history(daily_close_dir=daily, history_dir=history)
            self.assertEqual(points[-1].equity, 121.0)
            self.assertEqual(points[-1].cumulative_pnl, 21.0)
            self.assertAlmostEqual(points[-1].cumulative_return_pct, 21.0, places=6)

    def test_daily_return_pct_is_calculated_correctly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            daily = Path(tmp) / "daily_close"
            history = Path(tmp) / "history"
            self._write_daily_close(daily, as_of="2026-04-24T19:00:00", starting_equity=100.0, ending_equity=110.0, total_pnl=10.0, total_return_pct=0.1, fees_paid=0.1, fills_count=1, rejected_orders_count=0)
            update_crypto_paper_history(daily_close_dir=daily, history_dir=history)
            self._write_daily_close(daily, as_of="2026-04-25T19:00:00", starting_equity=110.0, ending_equity=121.0, total_pnl=11.0, total_return_pct=0.1, fees_paid=0.1, fills_count=1, rejected_orders_count=0)
            _, points, _, _, _, _ = update_crypto_paper_history(daily_close_dir=daily, history_dir=history)
            self.assertAlmostEqual(points[1].daily_return_pct, 10.0, places=6)

    def test_max_drawdown_is_calculated_correctly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            daily = Path(tmp) / "daily_close"
            history = Path(tmp) / "history"
            self._write_daily_close(daily, as_of="2026-04-24T19:00:00", starting_equity=100.0, ending_equity=110.0, total_pnl=10.0, total_return_pct=0.1, fees_paid=0.1, fills_count=1, rejected_orders_count=0)
            update_crypto_paper_history(daily_close_dir=daily, history_dir=history)
            self._write_daily_close(daily, as_of="2026-04-25T19:00:00", starting_equity=110.0, ending_equity=90.0, total_pnl=-20.0, total_return_pct=-0.181818, fees_paid=0.1, fills_count=1, rejected_orders_count=0)
            _, points, summary, _, _, _ = update_crypto_paper_history(daily_close_dir=daily, history_dir=history)
            self.assertAlmostEqual(points[-1].drawdown, -20.0, places=6)
            self.assertAlmostEqual(summary.max_drawdown_pct, -18.1818181818, places=4)

    def test_win_loss_flat_counts_and_win_rate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            daily = Path(tmp) / "daily_close"
            history = Path(tmp) / "history"
            configs = [
                ("2026-04-24T19:00:00", 100.0, 101.0),
                ("2026-04-25T19:00:00", 101.0, 100.0),
                ("2026-04-26T19:00:00", 100.0, 100.0),
            ]
            for as_of, start, end in configs:
                self._write_daily_close(daily, as_of=as_of, starting_equity=start, ending_equity=end, total_pnl=end - start, total_return_pct=((end - start) / start) if start else 0.0, fees_paid=0.1, fills_count=1, rejected_orders_count=0)
                update_crypto_paper_history(daily_close_dir=daily, history_dir=history)
            entries, points, summary, _, _, _ = update_crypto_paper_history(daily_close_dir=daily, history_dir=history)
            self.assertEqual(len(entries), 3)
            self.assertEqual(summary.winning_days, 1)
            self.assertEqual(summary.losing_days, 1)
            self.assertEqual(summary.flat_days, 1)
            self.assertAlmostEqual(summary.win_rate, 1 / 3, places=6)

    def test_total_fees_and_fills_are_aggregated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            daily = Path(tmp) / "daily_close"
            history = Path(tmp) / "history"
            self._write_daily_close(daily, as_of="2026-04-24T19:00:00", starting_equity=100.0, ending_equity=101.0, total_pnl=1.0, total_return_pct=0.01, fees_paid=0.2, fills_count=2, rejected_orders_count=1)
            update_crypto_paper_history(daily_close_dir=daily, history_dir=history)
            self._write_daily_close(daily, as_of="2026-04-25T19:00:00", starting_equity=101.0, ending_equity=102.0, total_pnl=1.0, total_return_pct=0.0099, fees_paid=0.3, fills_count=3, rejected_orders_count=2)
            _, _, summary, _, _, _ = update_crypto_paper_history(daily_close_dir=daily, history_dir=history)
            self.assertAlmostEqual(summary.total_fees_paid, 0.5, places=6)
            self.assertEqual(summary.total_fills, 5)
            self.assertEqual(summary.total_rejected_orders, 3)

    def test_symbol_attribution_is_limited_but_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            daily = Path(tmp) / "daily_close"
            history = Path(tmp) / "history"
            positions = [{"symbol": "BTCUSDT", "quantity": 0.1, "avg_entry_price": 100.0, "last_price": 105.0, "unrealized_pnl": 0.5}]
            self._write_daily_close(daily, as_of="2026-04-24T19:00:00", starting_equity=100.0, ending_equity=100.5, total_pnl=0.5, total_return_pct=0.005, fees_paid=0.1, fills_count=1, rejected_orders_count=0, positions=positions)
            entries, _, _, attribution, _, warnings = update_crypto_paper_history(daily_close_dir=daily, history_dir=history)
            self.assertEqual(len(entries), 1)
            self.assertEqual(attribution[0]["symbol"], "BTCUSDT")
            self.assertTrue(any("Limited symbol attribution" in warning for warning in warnings))

    def test_markdown_report_is_generated_and_serializable_outputs_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            daily = Path(tmp) / "daily_close"
            history = Path(tmp) / "history"
            self._write_daily_close(daily, as_of="2026-04-24T19:00:00", starting_equity=100.0, ending_equity=101.0, total_pnl=1.0, total_return_pct=0.01, fees_paid=0.1, fills_count=1, rejected_orders_count=0)
            entries, points, summary, attribution, artifacts, _ = update_crypto_paper_history(daily_close_dir=daily, history_dir=history)
            report = (history / "crypto_paper_history_report.md").read_text(encoding="utf-8")
            self.assertIn("# Crypto Paper Performance History", report)
            json.loads((history / "crypto_paper_performance_history.json").read_text(encoding="utf-8"))
            json.loads((history / "crypto_paper_equity_curve.json").read_text(encoding="utf-8"))
            json.loads((history / "crypto_paper_drawdown_series.json").read_text(encoding="utf-8"))
            json.loads((history / "crypto_paper_symbol_attribution.json").read_text(encoding="utf-8"))
            self.assertTrue(artifacts)
            self.assertFalse(summary.live_trading)
            self.assertTrue(all(entry.paper_only for entry in entries))
            self.assertFalse(any(entry.live_trading for entry in entries))

    def test_history_uses_realized_pnl_from_daily_close(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            daily = Path(tmp) / "daily_close"
            history = Path(tmp) / "history"
            self._write_daily_close(
                daily,
                as_of="2026-04-24T19:00:00",
                starting_equity=100.0,
                ending_equity=101.0,
                total_pnl=1.0,
                total_return_pct=0.01,
                fees_paid=0.1,
                fills_count=1,
                rejected_orders_count=0,
            )
            payload = json.loads((daily / "crypto_paper_performance_summary.json").read_text(encoding="utf-8"))
            payload["realized_pnl"] = 1.5
            (daily / "crypto_paper_performance_summary.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            entries, _, _, _, _, _ = update_crypto_paper_history(daily_close_dir=daily, history_dir=history)
            self.assertAlmostEqual(entries[0].realized_pnl, 1.5, places=6)


if __name__ == "__main__":
    unittest.main()
