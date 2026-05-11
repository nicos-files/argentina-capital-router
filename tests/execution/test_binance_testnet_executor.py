"""Tests for :mod:`src.execution.binance_testnet_executor`.

All HTTP calls are blocked: a fake broker client records every invocation and
no real network I/O happens. Covers:

- Env gates (``ENABLE_BINANCE_TESTNET_EXECUTION``, base-URL allowlist,
  credentials, max notional, allowed symbols).
- ``order_test`` mode vs real ``place_order`` mode dispatch.
- Idempotency / dedupe via the persisted state file.
- Artifact layout (testnet artifacts isolated from paper artifacts).
- Reconciliation between paper events and testnet orders.
- Live Binance hosts/endpoints rejected.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.execution.binance_testnet_executor import (
    ALLOWED_SYMBOLS_ENV,
    ARTIFACTS_SUBDIR,
    BASE_URL_ENV,
    DEFAULT_ALLOWED_SYMBOLS,
    DEFAULT_MAX_NOTIONAL,
    ENABLE_FLAG,
    MAX_NOTIONAL_ENV,
    ORDER_TEST_ONLY_FLAG,
    build_client_order_id,
    run_binance_testnet_execution,
)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _FakeClient:
    """Records every broker call. Never makes network I/O."""

    def __init__(
        self,
        *,
        order_test_response: dict[str, Any] | None = None,
        place_order_response: dict[str, Any] | None = None,
        api_key_masked: str = "****abcd",
        order_test_raises: BaseException | None = None,
        place_order_raises: BaseException | None = None,
    ) -> None:
        self.order_test_calls: list[Mapping[str, Any]] = []
        self.place_order_calls: list[Mapping[str, Any]] = []
        self._order_test_response = order_test_response or {}
        self._place_order_response = place_order_response or {
            "orderId": 999,
            "clientOrderId": "from-broker",
            "status": "FILLED",
            "transactTime": 1700000001000,
            "executedQty": "0.0003",
            "cummulativeQuoteQty": "25.0",
            "fills": [
                {
                    "price": "76026.5",
                    "qty": "0.0003",
                    "commission": "0.025",
                    "commissionAsset": "USDT",
                }
            ],
        }
        self._order_test_raises = order_test_raises
        self._place_order_raises = place_order_raises
        self.api_key_masked = api_key_masked

    def order_test(self, *, params: Mapping[str, Any]) -> dict[str, Any]:
        if self._order_test_raises is not None:
            raise self._order_test_raises
        self.order_test_calls.append(dict(params))
        return dict(self._order_test_response)

    def place_order(self, *, params: Mapping[str, Any]) -> dict[str, Any]:
        if self._place_order_raises is not None:
            raise self._place_order_raises
        self.place_order_calls.append(dict(params))
        return dict(self._place_order_response)


def _testnet_env(**overrides: str) -> dict[str, str]:
    base = {
        ENABLE_FLAG: "1",
        ORDER_TEST_ONLY_FLAG: "1",
        BASE_URL_ENV: "https://testnet.binance.vision",
        MAX_NOTIONAL_ENV: "25",
        ALLOWED_SYMBOLS_ENV: "BTCUSDT,ETHUSDT",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Fixtures: paper-side semantic events
# ---------------------------------------------------------------------------


class _ExecutorTestCase(unittest.TestCase):
    """Common scaffolding: writes pre-built semantic events under
    ``<paper>/semantic/`` so the executor uses them without rebuilding."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.paper_dir = root / "crypto_paper"
        self.testnet_dir = root / ARTIFACTS_SUBDIR
        (self.paper_dir / "semantic").mkdir(parents=True, exist_ok=True)
        self.now = datetime(2026, 5, 3, 18, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write_events(self, events: list[dict[str, Any]]) -> None:
        path = self.paper_dir / "semantic" / "crypto_semantic_events.json"
        path.write_text(json.dumps(events), encoding="utf-8")
        # The executor's loader reads both summary + events. A minimal summary
        # is enough.
        summary_path = self.paper_dir / "semantic" / "crypto_semantic_summary.json"
        summary_path.write_text(json.dumps({"paper_only": True}), encoding="utf-8")

    def _buy_event(
        self,
        *,
        event_id: str = "buy:fill-1:2026-05-03T17:00:00",
        symbol: str = "BTCUSDT",
        gross_notional: float = 25.0,
        fill_price: float = 76026.5,
    ) -> dict[str, Any]:
        return {
            "event_id": event_id,
            "event_type": "BUY_FILLED_PAPER",
            "symbol": symbol,
            "severity": "ACTION",
            "human_title": f"Paper BUY filled {symbol}",
            "metadata": {
                "fill_id": "fill-1",
                "order_id": "order-1",
                "quantity": 0.000329,
                "fill_price": fill_price,
                "gross_notional": gross_notional,
                "fee": 0.025,
                "stop_loss": 74505.0,
                "take_profit": 77107.0,
                "occurred_at": "2026-05-03T17:00:00",
            },
        }

    def _take_profit_event(
        self,
        *,
        event_id: str = "take_profit:exit-1:2026-05-03T17:45:00",
        symbol: str = "BTCUSDT",
        exit_quantity: float = 0.0003,
        fill_price: float = 77100.0,
    ) -> dict[str, Any]:
        return {
            "event_id": event_id,
            "event_type": "TAKE_PROFIT",
            "symbol": symbol,
            "severity": "ACTION",
            "human_title": f"Paper TAKE-PROFIT exit: {symbol}",
            "metadata": {
                "exit_id": "exit-1",
                "exit_quantity": exit_quantity,
                "trigger_price": fill_price,
                "fill_price": fill_price,
                "realized_pnl": 0.5,
                "fee": 0.075,
                "occurred_at": "2026-05-03T17:45:00",
            },
        }

    def _stop_loss_event(self) -> dict[str, Any]:
        ev = self._take_profit_event(
            event_id="stop_loss:exit-2:2026-05-03T17:55:00",
            fill_price=74000.0,
        )
        ev["event_type"] = "STOP_LOSS"
        ev["human_title"] = "Paper STOP-LOSS exit: BTCUSDT"
        ev["metadata"]["exit_id"] = "exit-2"
        ev["metadata"]["realized_pnl"] = -1.5
        ev["metadata"]["occurred_at"] = "2026-05-03T17:55:00"
        return ev

    def _read_artifact(self, filename: str) -> Any:
        path = self.testnet_dir / filename
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Gate tests
# ---------------------------------------------------------------------------


class EnableFlagGateTests(_ExecutorTestCase):
    def test_disabled_when_flag_missing(self) -> None:
        self._write_events([self._buy_event()])
        result = run_binance_testnet_execution(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env={},  # no enable flag
            client=_FakeClient(),
            now=self.now,
        )
        self.assertFalse(result["ok"])
        self.assertIn(ENABLE_FLAG, result.get("reason", ""))
        self.assertEqual(result["placed_count"], 0)
        self.assertEqual(result["test_ok_count"], 0)

    def test_disabled_when_flag_zero(self) -> None:
        self._write_events([self._buy_event()])
        client = _FakeClient()
        result = run_binance_testnet_execution(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=_testnet_env(**{ENABLE_FLAG: "0"}),
            client=client,
            now=self.now,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(client.order_test_calls, [])
        self.assertEqual(client.place_order_calls, [])

    def test_result_artifact_written_even_when_blocked(self) -> None:
        self._write_events([self._buy_event()])
        run_binance_testnet_execution(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env={},
            client=_FakeClient(),
            now=self.now,
        )
        payload = self._read_artifact("binance_testnet_execution_result.json")
        self.assertIsNotNone(payload)
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["live_trading"])
        self.assertTrue(payload["testnet"])


class BaseUrlGateTests(_ExecutorTestCase):
    def test_live_binance_url_is_rejected(self) -> None:
        self._write_events([self._buy_event()])
        client = _FakeClient()
        result = run_binance_testnet_execution(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=_testnet_env(**{BASE_URL_ENV: "https://api.binance.com"}),
            client=client,
            now=self.now,
        )
        self.assertFalse(result["ok"])
        self.assertIn("non-testnet", result.get("reason", ""))
        self.assertEqual(client.order_test_calls, [])
        self.assertEqual(client.place_order_calls, [])

    def test_futures_url_rejected(self) -> None:
        self._write_events([self._buy_event()])
        result = run_binance_testnet_execution(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=_testnet_env(**{BASE_URL_ENV: "https://fapi.binance.com"}),
            client=_FakeClient(),
            now=self.now,
        )
        self.assertFalse(result["ok"])
        self.assertIn("non-testnet", result.get("reason", ""))


class CredentialGateTests(_ExecutorTestCase):
    def test_missing_credentials_blocks_when_no_client(self) -> None:
        # No client provided and no env credentials => should refuse.
        self._write_events([self._buy_event()])
        result = run_binance_testnet_execution(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=_testnet_env(),  # no key/secret
            client=None,
            now=self.now,
        )
        self.assertFalse(result["ok"])
        self.assertIn("BINANCE_TESTNET_API_KEY", result.get("reason", ""))


# ---------------------------------------------------------------------------
# Mode dispatch
# ---------------------------------------------------------------------------


class OrderTestModeTests(_ExecutorTestCase):
    def test_buy_event_in_order_test_mode_calls_order_test_only(self) -> None:
        self._write_events([self._buy_event()])
        client = _FakeClient()
        result = run_binance_testnet_execution(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=_testnet_env(),
            client=client,
            now=self.now,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(len(client.order_test_calls), 1)
        self.assertEqual(client.place_order_calls, [])
        self.assertEqual(result["test_ok_count"], 1)
        self.assertEqual(result["placed_count"], 0)

        params = client.order_test_calls[0]
        self.assertEqual(params["symbol"], "BTCUSDT")
        self.assertEqual(params["side"], "BUY")
        self.assertEqual(params["type"], "MARKET")
        # MARKET BUY uses quoteOrderQty == requested notional.
        self.assertAlmostEqual(float(params["quoteOrderQty"]), 25.0, places=8)
        self.assertTrue(str(params["newClientOrderId"]).startswith("tnbuy-"))

    def test_take_profit_event_in_order_test_mode_uses_sell_quantity(self) -> None:
        self._write_events([self._take_profit_event()])
        client = _FakeClient()
        run_binance_testnet_execution(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=_testnet_env(),
            client=client,
            now=self.now,
        )
        self.assertEqual(len(client.order_test_calls), 1)
        self.assertEqual(client.place_order_calls, [])
        params = client.order_test_calls[0]
        self.assertEqual(params["side"], "SELL")
        self.assertEqual(params["symbol"], "BTCUSDT")
        self.assertNotIn("quoteOrderQty", params)
        self.assertAlmostEqual(float(params["quantity"]), 0.0003, places=8)
        self.assertTrue(str(params["newClientOrderId"]).startswith("tntp-"))


class RealPlaceOrderModeTests(_ExecutorTestCase):
    def test_real_mode_calls_place_order_and_records_fill(self) -> None:
        self._write_events([self._buy_event()])
        client = _FakeClient()
        result = run_binance_testnet_execution(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=_testnet_env(**{ORDER_TEST_ONLY_FLAG: "0"}),
            client=client,
            now=self.now,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(len(client.place_order_calls), 1)
        self.assertEqual(client.order_test_calls, [])
        self.assertEqual(result["placed_count"], 1)
        self.assertEqual(result["test_ok_count"], 0)

        fills = self._read_artifact("binance_testnet_fills.json")
        self.assertEqual(len(fills), 1)
        self.assertEqual(fills[0]["symbol"], "BTCUSDT")
        self.assertEqual(fills[0]["side"], "BUY")
        self.assertAlmostEqual(fills[0]["quantity"], 0.0003, places=8)


# ---------------------------------------------------------------------------
# Symbol allowlist + max notional
# ---------------------------------------------------------------------------


class SymbolAllowlistTests(_ExecutorTestCase):
    def test_disallowed_symbol_is_rejected_without_broker_call(self) -> None:
        self._write_events([self._buy_event(symbol="DOGEUSDT")])
        client = _FakeClient()
        result = run_binance_testnet_execution(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=_testnet_env(),  # only BTC + ETH allowed
            client=client,
            now=self.now,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(client.order_test_calls, [])
        self.assertEqual(result["rejected_count"], 1)
        orders = self._read_artifact("binance_testnet_orders.json")
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["status"], "REJECTED")
        self.assertIn("symbol_not_allowed", orders[0]["reason"])

    def test_custom_allowlist_overrides_default(self) -> None:
        self._write_events([self._buy_event(symbol="ETHUSDT")])
        client = _FakeClient()
        run_binance_testnet_execution(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=_testnet_env(**{ALLOWED_SYMBOLS_ENV: "ETHUSDT"}),
            client=client,
            now=self.now,
        )
        self.assertEqual(len(client.order_test_calls), 1)
        self.assertEqual(client.order_test_calls[0]["symbol"], "ETHUSDT")


class MaxNotionalTests(_ExecutorTestCase):
    def test_notional_above_cap_is_rejected_pre_call(self) -> None:
        self._write_events([self._buy_event(gross_notional=500.0)])
        client = _FakeClient()
        result = run_binance_testnet_execution(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=_testnet_env(**{MAX_NOTIONAL_ENV: "25"}),
            client=client,
            now=self.now,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(client.order_test_calls, [])
        self.assertEqual(result["rejected_count"], 1)
        orders = self._read_artifact("binance_testnet_orders.json")
        self.assertIn("notional_exceeds_max", orders[0]["reason"])

    def test_invalid_max_notional_falls_back_to_default(self) -> None:
        self._write_events([self._buy_event(gross_notional=DEFAULT_MAX_NOTIONAL)])
        client = _FakeClient()
        result = run_binance_testnet_execution(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=_testnet_env(**{MAX_NOTIONAL_ENV: "not-a-number"}),
            client=client,
            now=self.now,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["max_notional"], DEFAULT_MAX_NOTIONAL)
        self.assertEqual(len(client.order_test_calls), 1)
        self.assertTrue(
            any("invalid_binance_testnet_max_notional" in w for w in result["warnings"])
        )


# ---------------------------------------------------------------------------
# Idempotency / dedupe
# ---------------------------------------------------------------------------


class IdempotencyTests(_ExecutorTestCase):
    def test_same_event_id_is_skipped_on_second_run(self) -> None:
        events = [self._buy_event()]
        self._write_events(events)
        client_a = _FakeClient()
        run_binance_testnet_execution(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=_testnet_env(**{ORDER_TEST_ONLY_FLAG: "0"}),
            client=client_a,
            now=self.now,
        )
        self.assertEqual(len(client_a.place_order_calls), 1)

        # Second run with the same paper events => no new placement.
        client_b = _FakeClient()
        result = run_binance_testnet_execution(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=_testnet_env(**{ORDER_TEST_ONLY_FLAG: "0"}),
            client=client_b,
            now=self.now,
        )
        self.assertEqual(client_b.place_order_calls, [])
        self.assertEqual(result["placed_count"], 0)
        self.assertEqual(result["skipped_count"], 1)

    def test_new_event_after_dedupe_state_still_runs(self) -> None:
        # First run: BUY only.
        self._write_events([self._buy_event()])
        client_a = _FakeClient()
        run_binance_testnet_execution(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=_testnet_env(**{ORDER_TEST_ONLY_FLAG: "0"}),
            client=client_a,
            now=self.now,
        )
        self.assertEqual(len(client_a.place_order_calls), 1)

        # Second run: BUY + new TAKE_PROFIT. BUY skipped, TP placed.
        self._write_events([self._buy_event(), self._take_profit_event()])
        client_b = _FakeClient()
        result = run_binance_testnet_execution(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=_testnet_env(**{ORDER_TEST_ONLY_FLAG: "0"}),
            client=client_b,
            now=self.now,
        )
        self.assertEqual(len(client_b.place_order_calls), 1)
        self.assertEqual(client_b.place_order_calls[0]["side"], "SELL")
        self.assertEqual(result["skipped_count"], 1)
        self.assertEqual(result["placed_count"], 1)

    def test_client_order_id_is_deterministic_for_event_id(self) -> None:
        ev = {"event_id": "buy:abc:2026", "event_type": "BUY_FILLED_PAPER"}
        self.assertEqual(build_client_order_id(ev), build_client_order_id(ev))
        # Different event ids => different ids.
        ev2 = {"event_id": "buy:def:2026", "event_type": "BUY_FILLED_PAPER"}
        self.assertNotEqual(build_client_order_id(ev), build_client_order_id(ev2))
        # Length within the Binance 36-char limit.
        coid = build_client_order_id(ev)
        self.assertLessEqual(len(coid), 36)
        self.assertTrue(coid.startswith("tnbuy-"))


# ---------------------------------------------------------------------------
# Artifacts isolation + reconciliation
# ---------------------------------------------------------------------------


class ArtifactIsolationTests(_ExecutorTestCase):
    def test_testnet_artifacts_written_to_separate_dir(self) -> None:
        self._write_events([self._buy_event()])
        client = _FakeClient()
        run_binance_testnet_execution(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=_testnet_env(**{ORDER_TEST_ONLY_FLAG: "0"}),
            client=client,
            now=self.now,
        )
        self.assertTrue((self.testnet_dir / "binance_testnet_orders.json").exists())
        self.assertTrue((self.testnet_dir / "binance_testnet_fills.json").exists())
        self.assertTrue((self.testnet_dir / "binance_testnet_positions.json").exists())
        self.assertTrue(
            (self.testnet_dir / "binance_testnet_reconciliation.json").exists()
        )
        self.assertTrue(
            (self.testnet_dir / "binance_testnet_execution_result.json").exists()
        )
        # Paper artifacts must not gain testnet files.
        self.assertFalse((self.paper_dir / "binance_testnet_orders.json").exists())
        self.assertFalse((self.paper_dir / "binance_testnet_fills.json").exists())

    def test_paper_artifacts_are_not_modified(self) -> None:
        events_path = self.paper_dir / "semantic" / "crypto_semantic_events.json"
        original = [self._buy_event()]
        self._write_events(original)
        before = events_path.read_text(encoding="utf-8")

        run_binance_testnet_execution(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=_testnet_env(),
            client=_FakeClient(),
            now=self.now,
        )
        after = events_path.read_text(encoding="utf-8")
        self.assertEqual(before, after)


class ReconciliationTests(_ExecutorTestCase):
    def test_match_records_for_accepted_orders(self) -> None:
        self._write_events([self._buy_event()])
        run_binance_testnet_execution(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=_testnet_env(),
            client=_FakeClient(),
            now=self.now,
        )
        recon = self._read_artifact("binance_testnet_reconciliation.json")
        self.assertEqual(len(recon), 1)
        self.assertTrue(recon[0]["match"])
        self.assertEqual(recon[0]["paper_event_type"], "BUY_FILLED_PAPER")
        self.assertEqual(recon[0]["symbol"], "BTCUSDT")
        self.assertEqual(recon[0]["paper_side"], "BUY")
        self.assertEqual(recon[0]["testnet_status"], "TEST_OK")
        self.assertEqual(recon[0]["testnet_mode"], "order_test")

    def test_rejected_symbol_recon_flags_mismatch(self) -> None:
        self._write_events([self._buy_event(symbol="DOGEUSDT")])
        run_binance_testnet_execution(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=_testnet_env(),
            client=_FakeClient(),
            now=self.now,
        )
        recon = self._read_artifact("binance_testnet_reconciliation.json")
        self.assertEqual(len(recon), 1)
        self.assertFalse(recon[0]["match"])
        self.assertTrue(
            any("rejected:symbol_not_allowed" in m for m in recon[0]["mismatches"])
        )


# ---------------------------------------------------------------------------
# Broker error path
# ---------------------------------------------------------------------------


class BrokerErrorTests(_ExecutorTestCase):
    def test_broker_request_error_is_recorded_as_rejected_not_propagated(self) -> None:
        from src.brokers.binance_spot_testnet import BinanceTestnetRequestError

        self._write_events([self._buy_event()])
        client = _FakeClient(
            order_test_raises=BinanceTestnetRequestError("simulated outage")
        )
        result = run_binance_testnet_execution(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=_testnet_env(),
            client=client,
            now=self.now,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["test_ok_count"], 0)
        self.assertEqual(result["rejected_count"], 1)
        self.assertTrue(
            any("broker_error" in w for w in result["warnings"]),
            f"expected broker_error in warnings, got {result['warnings']!r}",
        )


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


class DryRunTests(_ExecutorTestCase):
    def test_dry_run_does_not_call_broker_even_when_enabled(self) -> None:
        self._write_events([self._buy_event()])
        client = _FakeClient()
        result = run_binance_testnet_execution(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=_testnet_env(),
            client=client,
            now=self.now,
            dry_run=True,
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(client.order_test_calls, [])
        self.assertEqual(client.place_order_calls, [])
        self.assertEqual(result["skipped_count"], 1)


# ---------------------------------------------------------------------------
# Defaults / config plumbing
# ---------------------------------------------------------------------------


class ConfigDefaultsTests(_ExecutorTestCase):
    def test_default_allowed_symbols_when_env_missing(self) -> None:
        self._write_events([self._buy_event()])
        env = {ENABLE_FLAG: "1"}  # nothing else
        result = run_binance_testnet_execution(
            paper_artifacts_dir=self.paper_dir,
            testnet_artifacts_dir=self.testnet_dir,
            env=env,
            client=_FakeClient(),
            now=self.now,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(tuple(result["allowed_symbols"]), DEFAULT_ALLOWED_SYMBOLS)
        self.assertEqual(result["max_notional"], DEFAULT_MAX_NOTIONAL)

    def test_live_trading_field_always_false(self) -> None:
        self._write_events([self._buy_event()])
        for env in (
            {},
            _testnet_env(),
            _testnet_env(**{ORDER_TEST_ONLY_FLAG: "0"}),
        ):
            result = run_binance_testnet_execution(
                paper_artifacts_dir=self.paper_dir,
                testnet_artifacts_dir=self.testnet_dir,
                env=env,
                client=_FakeClient(),
                now=self.now,
            )
            self.assertFalse(result["live_trading"], f"live_trading flipped for env={env!r}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
