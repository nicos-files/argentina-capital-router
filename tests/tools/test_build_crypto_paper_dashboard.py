import json
import socket
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.tools.build_crypto_paper_dashboard import build_crypto_paper_dashboard, main


class BuildCryptoPaperDashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.artifacts_dir = Path(self._tmp.name) / "crypto_paper"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        (self.artifacts_dir / "evaluation").mkdir(exist_ok=True)
        (self.artifacts_dir / "history").mkdir(exist_ok=True)
        (self.artifacts_dir / "paper_forward").mkdir(exist_ok=True)
        self.dashboard_dir = self.artifacts_dir / "dashboard"
        self.now = datetime(2026, 5, 3, 18, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _seed_minimal_artifacts(self) -> None:
        snapshot = {
            "as_of": "2026-05-03T17:45:00",
            "equity": 100.642299,
            "cash": 100.642299,
            "positions_value": 0.0,
            "realized_pnl": 0.717299,
            "unrealized_pnl": 0.0,
            "fees_paid": 0.150793,
            "positions": [],
        }
        metrics = {
            "closed_trades_count": 3,
            "open_trades_count": 0,
            "win_rate": 1.0,
            "expectancy": 0.214,
            "profit_factor": None,
            "net_profit": 0.642299,
            "total_fees": 0.150793,
            "total_slippage": 0.075,
            "stop_loss_count": 0,
            "take_profit_count": 3,
            "warnings": ["Small sample size: fewer than 30 closed trades."],
        }
        equity_curve = [{"equity": 100.0, "as_of": "2026-04-28T13:56:54"}]
        fills = [
            {
                "fill_id": "crypto-paper-fill-20260428T150008-0001",
                "order_id": "crypto-paper-order-20260428T150008-0001",
                "symbol": "BTCUSDT",
                "side": "BUY",
                "quantity": 0.000328,
                "fill_price": 76026.5,
                "gross_notional": 25.0,
                "fee": 0.025,
                "filled_at": "2026-04-28T15:00:08",
                "metadata": {"stop_loss": 74468.7, "take_profit": 76748.4},
            }
        ]
        exits = [
            {
                "exit_id": "crypto-exit-BTCUSDT-20260503T174500-0001",
                "symbol": "BTCUSDT",
                "exit_reason": "TAKE_PROFIT",
                "exit_quantity": 0.001,
                "trigger_price": 77131.478,
                "fill_price": 77092.91,
                "realized_pnl": 0.717,
                "fee": 0.075,
                "exited_at": "2026-05-03T17:45:00",
                "source": "stop_take_quote_fallback",
                "metadata": {"stop_loss": 74840.0, "take_profit": 77131.478},
            }
        ]
        orders = [
            {
                "order_id": "crypto-paper-order-20260430T230009-0001",
                "symbol": "BTCUSDT",
                "side": "BUY",
                "status": "REJECTED",
                "reason": "risk:cash_insufficient",
                "reference_price": 76323.24,
                "requested_notional": 25.0,
                "created_at": "2026-04-30T23:00:09",
                "metadata": {},
            }
        ]
        (self.artifacts_dir / "crypto_paper_snapshot.json").write_text(
            json.dumps(snapshot), encoding="utf-8"
        )
        (self.artifacts_dir / "crypto_paper_positions.json").write_text("[]", encoding="utf-8")
        (self.artifacts_dir / "crypto_paper_fills.json").write_text(
            json.dumps(fills), encoding="utf-8"
        )
        (self.artifacts_dir / "crypto_paper_orders.json").write_text(
            json.dumps(orders), encoding="utf-8"
        )
        (self.artifacts_dir / "crypto_paper_exit_events.json").write_text(
            json.dumps(exits), encoding="utf-8"
        )
        (self.artifacts_dir / "evaluation" / "crypto_paper_strategy_metrics.json").write_text(
            json.dumps(metrics), encoding="utf-8"
        )
        (self.artifacts_dir / "history" / "crypto_paper_equity_curve.json").write_text(
            json.dumps(equity_curve), encoding="utf-8"
        )

    def test_dashboard_writes_index_html(self) -> None:
        self._seed_minimal_artifacts()
        result = build_crypto_paper_dashboard(
            artifacts_dir=self.artifacts_dir,
            dashboard_dir=self.dashboard_dir,
            now=self.now,
        )
        index_path = self.dashboard_dir / "index.html"
        self.assertTrue(index_path.exists())
        content = index_path.read_text(encoding="utf-8")
        self.assertTrue(content.startswith("<!DOCTYPE html>"))
        self.assertIn("Crypto Paper Dashboard", content)
        self.assertEqual(result["artifacts"]["index_html"], str(index_path))

    def test_dashboard_writes_dashboard_data_json(self) -> None:
        self._seed_minimal_artifacts()
        build_crypto_paper_dashboard(
            artifacts_dir=self.artifacts_dir,
            dashboard_dir=self.dashboard_dir,
            now=self.now,
        )
        data_path = self.dashboard_dir / "dashboard_data.json"
        self.assertTrue(data_path.exists())
        payload = json.loads(data_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["paper_only"], True)
        self.assertEqual(payload["live_trading"], False)
        self.assertIn("snapshot", payload)
        self.assertIn("performance", payload)
        self.assertIn("recent_events", payload)

    def test_dashboard_writes_latest_summary_markdown(self) -> None:
        self._seed_minimal_artifacts()
        build_crypto_paper_dashboard(
            artifacts_dir=self.artifacts_dir,
            dashboard_dir=self.dashboard_dir,
            now=self.now,
        )
        summary_path = self.dashboard_dir / "latest_summary.md"
        self.assertTrue(summary_path.exists())
        content = summary_path.read_text(encoding="utf-8")
        self.assertIn("# Crypto Paper Dashboard Summary", content)
        self.assertIn("Paper-only", content)

    def test_dashboard_contains_equity_pnl_and_trade_metrics(self) -> None:
        self._seed_minimal_artifacts()
        build_crypto_paper_dashboard(
            artifacts_dir=self.artifacts_dir,
            dashboard_dir=self.dashboard_dir,
            now=self.now,
        )
        content = (self.dashboard_dir / "index.html").read_text(encoding="utf-8")
        self.assertIn("Equity", content)
        self.assertIn("Realized P&amp;L", content)
        self.assertIn("Unrealized P&amp;L", content)
        self.assertIn("Closed trades", content)
        self.assertIn("Win rate", content)
        self.assertIn("Expectancy", content)
        self.assertIn("Take-profits", content)
        self.assertIn("Stop-losses", content)
        self.assertIn("Rejected orders", content)
        self.assertIn("Total fees", content)
        self.assertIn("Total slippage", content)
        self.assertIn("BTCUSDT", content)
        self.assertIn("TAKE_PROFIT", content)
        self.assertIn("Small sample size", content)

    def test_dashboard_includes_paper_only_disclaimer(self) -> None:
        self._seed_minimal_artifacts()
        build_crypto_paper_dashboard(
            artifacts_dir=self.artifacts_dir,
            dashboard_dir=self.dashboard_dir,
            now=self.now,
        )
        content = (self.dashboard_dir / "index.html").read_text(encoding="utf-8")
        self.assertIn("Paper-only", content)
        self.assertIn("manual-review", content)
        self.assertNotIn("live trading", content.lower().replace("no live trading", ""))

    def test_dashboard_does_not_require_network(self) -> None:
        # Block all socket activity during dashboard build.
        self._seed_minimal_artifacts()

        original_socket = socket.socket

        def _no_network(*args, **kwargs):  # noqa: ANN001
            raise AssertionError("dashboard build must not perform network IO")

        with patch("socket.socket", _no_network):
            try:
                build_crypto_paper_dashboard(
                    artifacts_dir=self.artifacts_dir,
                    dashboard_dir=self.dashboard_dir,
                    now=self.now,
                )
            finally:
                # Defensive: restore even if patch contextmanager already does it.
                socket.socket = original_socket

    def test_dashboard_handles_empty_artifacts_directory_gracefully(self) -> None:
        result = build_crypto_paper_dashboard(
            artifacts_dir=self.artifacts_dir,
            dashboard_dir=self.dashboard_dir,
            now=self.now,
        )
        self.assertTrue(result["ok"])
        self.assertTrue((self.dashboard_dir / "index.html").exists())
        payload = json.loads((self.dashboard_dir / "dashboard_data.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["snapshot"]["open_positions_count"], 0)

    def test_dashboard_does_not_reference_external_cdn(self) -> None:
        self._seed_minimal_artifacts()
        build_crypto_paper_dashboard(
            artifacts_dir=self.artifacts_dir,
            dashboard_dir=self.dashboard_dir,
            now=self.now,
        )
        content = (self.dashboard_dir / "index.html").read_text(encoding="utf-8").lower()
        for forbidden in ("https://", "http://", "cdn.", "<script", "src="):
            self.assertNotIn(
                forbidden,
                content,
                f"dashboard html must not reference external resources: found {forbidden!r}",
            )

    def test_main_cli_returns_zero_and_writes_files(self) -> None:
        self._seed_minimal_artifacts()
        rc = main([
            "--artifacts-dir", str(self.artifacts_dir),
            "--dashboard-dir", str(self.dashboard_dir),
        ])
        self.assertEqual(rc, 0)
        self.assertTrue((self.dashboard_dir / "index.html").exists())


class BuildCryptoPaperDashboardSignalOnlyTests(unittest.TestCase):
    """Dashboard surfaces SIGNAL_ONLY count and recent SIGNAL_ONLY events."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.artifacts_dir = Path(self._tmp.name) / "crypto_paper"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        (self.artifacts_dir / "evaluation").mkdir(exist_ok=True)
        (self.artifacts_dir / "history").mkdir(exist_ok=True)
        (self.artifacts_dir / "paper_forward").mkdir(exist_ok=True)
        self.dashboard_dir = self.artifacts_dir / "dashboard"
        self.now = datetime(2026, 5, 5, 23, 30, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _seed_with_signal_only(self) -> None:
        order = {
            "order_id": "crypto-paper-order-20260505T123007-0001",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "status": "REJECTED",
            "reason": "risk:cash_insufficient",
            "reference_price": 81482.11,
            "requested_notional": 25.0,
            "created_at": "2026-05-05T12:30:07",
            "metadata": {"stop_loss": 79812.56, "take_profit": 82255.80},
        }
        snapshot = {
            "as_of": "2026-05-05T23:30:00",
            "equity": 100.0,
            "cash": 100.0,
            "positions_value": 0.0,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "fees_paid": 0.0,
            "positions": [],
        }
        (self.artifacts_dir / "crypto_paper_orders.json").write_text(
            json.dumps([order]), encoding="utf-8"
        )
        (self.artifacts_dir / "crypto_paper_fills.json").write_text("[]", encoding="utf-8")
        (self.artifacts_dir / "crypto_paper_snapshot.json").write_text(
            json.dumps(snapshot), encoding="utf-8"
        )
        (self.artifacts_dir / "crypto_paper_positions.json").write_text("[]", encoding="utf-8")
        (self.artifacts_dir / "crypto_paper_exit_events.json").write_text("[]", encoding="utf-8")
        (self.artifacts_dir / "paper_forward" / "crypto_paper_forward_result.json").write_text(
            json.dumps(
                {
                    "recommendations_count": 1,
                    "fills_count": 0,
                    "exits_count": 0,
                    "status": "SUCCESS",
                }
            ),
            encoding="utf-8",
        )

    def test_dashboard_data_includes_signal_only_count_and_recent(self) -> None:
        self._seed_with_signal_only()
        result = build_crypto_paper_dashboard(
            artifacts_dir=self.artifacts_dir,
            dashboard_dir=self.dashboard_dir,
            rebuild_semantic=True,
            now=self.now,
        )
        data = result["data"]
        self.assertEqual(data["performance"]["signal_only_count"], 1)
        recent = data["recent_signal_only_events"]
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["symbol"], "BTCUSDT")
        self.assertEqual(
            (recent[0].get("metadata") or {}).get("rejection_reason"),
            "risk:cash_insufficient",
        )

    def test_dashboard_html_renders_signal_only_card_and_section(self) -> None:
        self._seed_with_signal_only()
        build_crypto_paper_dashboard(
            artifacts_dir=self.artifacts_dir,
            dashboard_dir=self.dashboard_dir,
            rebuild_semantic=True,
            now=self.now,
        )
        content = (self.dashboard_dir / "index.html").read_text(encoding="utf-8")
        # Card and section are present.
        self.assertIn("Signal-only", content)
        self.assertIn("Recent SIGNAL_ONLY events", content)
        # The seeded SIGNAL_ONLY symbol appears in the recent table.
        self.assertIn("BTCUSDT", content)
        # Markdown summary also includes the Signal-only line.
        md_content = (self.dashboard_dir / "latest_summary.md").read_text(encoding="utf-8")
        self.assertIn("Signal-only", md_content)


class BuildCryptoPaperDashboardTestnetSectionTests(unittest.TestCase):
    """Dashboard surfaces a read-only Binance Spot Testnet section when
    ``crypto_testnet`` artifacts are present. Paper-only artifacts must be
    untouched, the section is omitted otherwise, and ``live_trading`` stays
    ``False`` everywhere."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.artifacts_dir = self.root / "crypto_paper"
        self.testnet_dir = self.root / "crypto_testnet"
        self.dashboard_dir = self.artifacts_dir / "dashboard"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.testnet_dir.mkdir(parents=True, exist_ok=True)
        self.now = datetime(2026, 5, 5, 23, 30, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _seed_paper_minimum(self) -> None:
        snapshot = {
            "as_of": "2026-05-05T23:00:00",
            "equity": 100.0,
            "cash": 100.0,
            "positions_value": 0.0,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "fees_paid": 0.0,
            "positions": [],
        }
        (self.artifacts_dir / "crypto_paper_snapshot.json").write_text(
            json.dumps(snapshot), encoding="utf-8"
        )
        (self.artifacts_dir / "crypto_paper_positions.json").write_text(
            "[]", encoding="utf-8"
        )

    def _seed_testnet(
        self,
        *,
        order_test_only: bool = True,
        api_key_masked: str = "****abcd",
    ) -> None:
        orders = [
            {
                "client_order_id": "tnbuy-deadbeefdeadbeefdeadbeef",
                "symbol": "BTCUSDT",
                "side": "BUY",
                "type": "MARKET",
                "quantity": None,
                "quote_order_qty": 25.0,
                "requested_notional": 25.0,
                "reference_price": 76000.0,
                "paper_event_id": "buy:fill-1:2026",
                "paper_event_type": "BUY_FILLED_PAPER",
                "mode": "order_test" if order_test_only else "place_order",
                "status": "TEST_OK" if order_test_only else "FILLED",
                "reason": None,
                "created_at": "2026-05-05T22:00:00+00:00",
                "metadata": {},
            },
            {
                "client_order_id": "tnbuy-rejected",
                "symbol": "DOGEUSDT",
                "side": "BUY",
                "type": "MARKET",
                "quantity": None,
                "quote_order_qty": None,
                "requested_notional": 25.0,
                "reference_price": 0.1,
                "paper_event_id": "buy:fill-2:2026",
                "paper_event_type": "BUY_FILLED_PAPER",
                "mode": "order_test" if order_test_only else "place_order",
                "status": "REJECTED",
                "reason": "symbol_not_allowed:DOGEUSDT",
                "created_at": "2026-05-05T22:01:00+00:00",
                "metadata": {},
            },
        ]
        fills = (
            []
            if order_test_only
            else [
                {
                    "fill_id": "tn-tnbuy-deadbeef",
                    "client_order_id": "tnbuy-deadbeefdeadbeefdeadbeef",
                    "binance_order_id": 9999,
                    "symbol": "BTCUSDT",
                    "side": "BUY",
                    "quantity": 0.0003,
                    "price": 76000.0,
                    "commission": 0.025,
                    "commission_asset": "USDT",
                    "status": "FILLED",
                    "transact_time_ms": 1700000001000,
                    "filled_at": "2026-05-05T22:00:01+00:00",
                    "metadata": {},
                }
            ]
        )
        positions = (
            []
            if order_test_only
            else [
                {
                    "symbol": "BTCUSDT",
                    "quantity": 0.0003,
                    "avg_entry_price": 76000.0,
                    "last_event_at": "2026-05-05T22:00:01+00:00",
                    "metadata": {},
                }
            ]
        )
        reconciliation = [
            {
                "paper_event_id": "buy:fill-1:2026",
                "paper_event_type": "BUY_FILLED_PAPER",
                "symbol": "BTCUSDT",
                "paper_side": "BUY",
                "expected_notional": 25.0,
                "testnet_client_order_id": "tnbuy-deadbeefdeadbeefdeadbeef",
                "testnet_status": "TEST_OK" if order_test_only else "FILLED",
                "testnet_mode": "order_test" if order_test_only else "place_order",
                "match": True,
                "mismatches": [],
                "metadata": {},
            }
        ]
        result = {
            "ok": True,
            "testnet": True,
            "live_trading": False,
            "order_test_only": order_test_only,
            "base_url": "https://testnet.binance.vision",
            "max_notional": 25.0,
            "allowed_symbols": ["BTCUSDT", "ETHUSDT"],
            "considered_count": 2,
            "placed_count": 0 if order_test_only else 1,
            "test_ok_count": 1 if order_test_only else 0,
            "rejected_count": 1,
            "skipped_count": 0,
            "warnings": [],
            "api_key_masked": api_key_masked,
            "testnet_artifacts_dir": str(self.testnet_dir),
        }
        (self.testnet_dir / "binance_testnet_orders.json").write_text(
            json.dumps(orders), encoding="utf-8"
        )
        (self.testnet_dir / "binance_testnet_fills.json").write_text(
            json.dumps(fills), encoding="utf-8"
        )
        (self.testnet_dir / "binance_testnet_positions.json").write_text(
            json.dumps(positions), encoding="utf-8"
        )
        (self.testnet_dir / "binance_testnet_reconciliation.json").write_text(
            json.dumps(reconciliation), encoding="utf-8"
        )
        (self.testnet_dir / "binance_testnet_execution_result.json").write_text(
            json.dumps(result), encoding="utf-8"
        )

    def test_section_absent_when_no_testnet_artifacts(self) -> None:
        self._seed_paper_minimum()
        result = build_crypto_paper_dashboard(
            artifacts_dir=self.artifacts_dir,
            dashboard_dir=self.dashboard_dir,
            testnet_artifacts_dir=self.testnet_dir,  # empty dir => no artifacts
            now=self.now,
        )
        self.assertFalse(result["data"]["testnet"]["present"])
        html_content = (self.dashboard_dir / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("Binance Spot Testnet", html_content)
        self.assertEqual(result["data"]["live_trading"], False)

    def test_section_renders_in_order_test_mode(self) -> None:
        self._seed_paper_minimum()
        self._seed_testnet(order_test_only=True)
        result = build_crypto_paper_dashboard(
            artifacts_dir=self.artifacts_dir,
            dashboard_dir=self.dashboard_dir,
            testnet_artifacts_dir=self.testnet_dir,
            now=self.now,
        )
        section = result["data"]["testnet"]
        self.assertTrue(section["present"])
        self.assertTrue(section["order_test_only"])
        self.assertEqual(section["test_ok_count"], 1)
        self.assertEqual(section["placed_count"], 0)
        self.assertEqual(section["rejected_count"], 1)
        self.assertEqual(section["api_key_masked"], "****abcd")
        self.assertEqual(section["base_url"], "https://testnet.binance.vision")

        html_content = (self.dashboard_dir / "index.html").read_text(encoding="utf-8")
        self.assertIn("Binance Spot Testnet", html_content)
        self.assertIn("order/test", html_content)
        self.assertIn("****abcd", html_content)
        self.assertIn("BTCUSDT", html_content)
        self.assertIn("symbol_not_allowed:DOGEUSDT", html_content)

    def test_section_renders_in_real_place_order_mode(self) -> None:
        self._seed_paper_minimum()
        self._seed_testnet(order_test_only=False)
        result = build_crypto_paper_dashboard(
            artifacts_dir=self.artifacts_dir,
            dashboard_dir=self.dashboard_dir,
            testnet_artifacts_dir=self.testnet_dir,
            now=self.now,
        )
        section = result["data"]["testnet"]
        self.assertTrue(section["present"])
        self.assertFalse(section["order_test_only"])
        self.assertEqual(section["placed_count"], 1)
        self.assertEqual(section["fills_count"], 1)
        self.assertEqual(len(section["positions"]), 1)
        html_content = (self.dashboard_dir / "index.html").read_text(encoding="utf-8")
        self.assertIn("place_order (real testnet)", html_content)
        # live_trading must remain False even in real testnet mode.
        self.assertFalse(result["data"]["live_trading"])

    def test_summary_markdown_includes_testnet_block_when_present(self) -> None:
        self._seed_paper_minimum()
        self._seed_testnet(order_test_only=True)
        build_crypto_paper_dashboard(
            artifacts_dir=self.artifacts_dir,
            dashboard_dir=self.dashboard_dir,
            testnet_artifacts_dir=self.testnet_dir,
            now=self.now,
        )
        md = (self.dashboard_dir / "latest_summary.md").read_text(encoding="utf-8")
        self.assertIn("Binance Spot Testnet", md)
        self.assertIn("order/test", md)
        self.assertIn("Test OK: 1", md)
        self.assertIn("Rejected: 1", md)

    def test_dashboard_does_not_modify_testnet_artifacts(self) -> None:
        self._seed_paper_minimum()
        self._seed_testnet(order_test_only=True)
        before = {
            path.name: path.read_text(encoding="utf-8")
            for path in self.testnet_dir.iterdir()
            if path.is_file()
        }
        build_crypto_paper_dashboard(
            artifacts_dir=self.artifacts_dir,
            dashboard_dir=self.dashboard_dir,
            testnet_artifacts_dir=self.testnet_dir,
            now=self.now,
        )
        after = {
            path.name: path.read_text(encoding="utf-8")
            for path in self.testnet_dir.iterdir()
            if path.is_file()
        }
        self.assertEqual(before, after)

    def test_default_testnet_dir_is_sibling_crypto_testnet(self) -> None:
        # Don't pass testnet_artifacts_dir => the dashboard should fall back
        # to <artifacts_dir>/../crypto_testnet, which is self.testnet_dir.
        self._seed_paper_minimum()
        self._seed_testnet(order_test_only=True)
        result = build_crypto_paper_dashboard(
            artifacts_dir=self.artifacts_dir,
            dashboard_dir=self.dashboard_dir,
            now=self.now,
        )
        self.assertTrue(result["data"]["testnet"]["present"])

    def test_html_remains_offline_with_testnet_section(self) -> None:
        self._seed_paper_minimum()
        self._seed_testnet(order_test_only=False)
        build_crypto_paper_dashboard(
            artifacts_dir=self.artifacts_dir,
            dashboard_dir=self.dashboard_dir,
            testnet_artifacts_dir=self.testnet_dir,
            now=self.now,
        )
        content = (self.dashboard_dir / "index.html").read_text(encoding="utf-8").lower()
        # The base_url string is present once in the testnet meta line, but
        # the page must not include script/CDN references.
        for forbidden in ("cdn.", "<script", " src="):
            self.assertNotIn(forbidden, content)


if __name__ == "__main__":
    unittest.main()
