"""Tests for :mod:`src.tools.notify_binance_testnet_telegram`.

The dispatcher must:

- refuse to send unless ``ENABLE_BINANCE_TESTNET_TELEGRAM_ALERTS=1``,
- only read testnet artifacts (never paper or live state),
- always include the TESTNET disclaimer and the "no live trading" framing,
- never log or embed the bot token,
- dedupe by ``client_order_id`` across runs,
- handle send failures gracefully (record warning, leave dedupe state intact).
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.notifications.telegram_notifier import TelegramSendError
from src.tools.notify_binance_testnet_telegram import (
    ENABLE_FLAG,
    main,
    render_testnet_order_message,
    run_testnet_telegram_alerts,
)


_TOKEN = "999:AAA-secret-token-do-not-leak"
_CHAT_ID = "1234567890"


class _RecordingSender:
    def __init__(self, *, raises_for: set[str] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.raises_for = raises_for or set()

    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        coid = ""
        text = str(kwargs.get("text") or "")
        # Tests inject the client_order_id substring so we can selectively
        # error one message in a batch.
        for marker in self.raises_for:
            if marker in text:
                raise TelegramSendError(f"simulated failure for {marker}")
        self.calls.append(dict(kwargs))
        return {"ok": True}


def _enabled_env(**overrides: str) -> dict[str, str]:
    base = {
        ENABLE_FLAG: "1",
        "TELEGRAM_BOT_TOKEN": _TOKEN,
        "TELEGRAM_CHAT_ID": _CHAT_ID,
    }
    base.update(overrides)
    return base


class _DispatcherCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.testnet_dir = Path(self._tmp.name) / "crypto_testnet"
        self.testnet_dir.mkdir(parents=True, exist_ok=True)
        self.now = datetime(2026, 5, 5, 23, 30, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _accepted_order(
        self,
        *,
        client_order_id: str = "tnbuy-aaaaaaaaaaaaaaaaaaaaaaaa",
        order_test: bool = True,
    ) -> dict[str, Any]:
        return {
            "client_order_id": client_order_id,
            "symbol": "BTCUSDT",
            "side": "BUY",
            "type": "MARKET",
            "quantity": None,
            "quote_order_qty": 25.0,
            "requested_notional": 25.0,
            "reference_price": 76000.0,
            "paper_event_id": "buy:fill-1:2026-05-05T22:00:00",
            "paper_event_type": "BUY_FILLED_PAPER",
            "mode": "order_test" if order_test else "place_order",
            "status": "TEST_OK" if order_test else "FILLED",
            "reason": None,
            "created_at": "2026-05-05T22:00:00+00:00",
            "metadata": {},
        }

    def _rejected_order(
        self, *, client_order_id: str = "tnbuy-rejected-bbbb"
    ) -> dict[str, Any]:
        return {
            "client_order_id": client_order_id,
            "symbol": "DOGEUSDT",
            "side": "BUY",
            "type": "MARKET",
            "quantity": None,
            "quote_order_qty": None,
            "requested_notional": 25.0,
            "reference_price": 0.1,
            "paper_event_id": "buy:fill-2:2026-05-05T22:01:00",
            "paper_event_type": "BUY_FILLED_PAPER",
            "mode": "order_test",
            "status": "REJECTED",
            "reason": "symbol_not_allowed:DOGEUSDT",
            "created_at": "2026-05-05T22:01:00+00:00",
            "metadata": {},
        }

    def _write_orders(self, orders: list[dict[str, Any]]) -> None:
        (self.testnet_dir / "binance_testnet_orders.json").write_text(
            json.dumps(orders), encoding="utf-8"
        )

    def _write_result(self, payload: dict[str, Any]) -> None:
        (self.testnet_dir / "binance_testnet_execution_result.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )


class EnableFlagTests(_DispatcherCase):
    def test_disabled_when_flag_missing(self) -> None:
        self._write_orders([self._accepted_order()])
        sender = _RecordingSender()
        result = run_testnet_telegram_alerts(
            testnet_artifacts_dir=self.testnet_dir,
            env={},  # no flag
            sender=sender,
            now=self.now,
        )
        self.assertFalse(result["ok"])
        self.assertIn(ENABLE_FLAG, result["reason"])
        self.assertEqual(sender.calls, [])

    def test_disabled_when_flag_zero(self) -> None:
        self._write_orders([self._accepted_order()])
        sender = _RecordingSender()
        result = run_testnet_telegram_alerts(
            testnet_artifacts_dir=self.testnet_dir,
            env=_enabled_env(**{ENABLE_FLAG: "0"}),
            sender=sender,
            now=self.now,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(sender.calls, [])


class MissingArtifactsTests(_DispatcherCase):
    def test_missing_dir_is_handled(self) -> None:
        sender = _RecordingSender()
        result = run_testnet_telegram_alerts(
            testnet_artifacts_dir=self.testnet_dir / "does_not_exist",
            env=_enabled_env(),
            sender=sender,
            now=self.now,
        )
        self.assertFalse(result["ok"])
        self.assertIn("not found", result["reason"])
        self.assertEqual(sender.calls, [])

    def test_no_orders_returns_ok_no_send(self) -> None:
        # dir exists but empty.
        sender = _RecordingSender()
        result = run_testnet_telegram_alerts(
            testnet_artifacts_dir=self.testnet_dir,
            env=_enabled_env(),
            sender=sender,
            now=self.now,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["sent_count"], 0)
        self.assertEqual(sender.calls, [])


class SendFlowTests(_DispatcherCase):
    def test_accepted_order_sent_in_order_test_mode(self) -> None:
        self._write_orders([self._accepted_order(order_test=True)])
        self._write_result({"base_url": "https://testnet.binance.vision"})
        sender = _RecordingSender()
        result = run_testnet_telegram_alerts(
            testnet_artifacts_dir=self.testnet_dir,
            env=_enabled_env(),
            sender=sender,
            now=self.now,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["sent_count"], 1)
        self.assertEqual(len(sender.calls), 1)
        text = sender.calls[0]["text"]
        self.assertIn("TESTNET TEST OK", text)
        self.assertIn("BTCUSDT", text)
        self.assertIn("BUY", text)
        self.assertIn("TESTNET only", text)
        self.assertIn("No live trading", text)
        self.assertEqual(sender.calls[0]["bot_token"], _TOKEN)
        self.assertEqual(sender.calls[0]["chat_id"], _CHAT_ID)
        self.assertEqual(sender.calls[0]["parse_mode"], "HTML")

    def test_real_place_order_uses_placed_label(self) -> None:
        self._write_orders([self._accepted_order(order_test=False)])
        sender = _RecordingSender()
        run_testnet_telegram_alerts(
            testnet_artifacts_dir=self.testnet_dir,
            env=_enabled_env(),
            sender=sender,
            now=self.now,
        )
        self.assertEqual(len(sender.calls), 1)
        text = sender.calls[0]["text"]
        self.assertIn("TESTNET PLACED", text)

    def test_rejected_order_uses_rejected_label(self) -> None:
        self._write_orders([self._rejected_order()])
        sender = _RecordingSender()
        run_testnet_telegram_alerts(
            testnet_artifacts_dir=self.testnet_dir,
            env=_enabled_env(),
            sender=sender,
            now=self.now,
        )
        self.assertEqual(len(sender.calls), 1)
        text = sender.calls[0]["text"]
        self.assertIn("TESTNET REJECTED", text)
        self.assertIn("symbol_not_allowed:DOGEUSDT", text)


class DedupeTests(_DispatcherCase):
    def test_already_sent_orders_are_skipped(self) -> None:
        order = self._accepted_order(client_order_id="tnbuy-coid-1234")
        self._write_orders([order])
        sender = _RecordingSender()
        first = run_testnet_telegram_alerts(
            testnet_artifacts_dir=self.testnet_dir,
            env=_enabled_env(),
            sender=sender,
            now=self.now,
        )
        self.assertEqual(first["sent_count"], 1)

        # Second call: state file remembers the COID; nothing new is sent.
        sender_b = _RecordingSender()
        second = run_testnet_telegram_alerts(
            testnet_artifacts_dir=self.testnet_dir,
            env=_enabled_env(),
            sender=sender_b,
            now=self.now,
        )
        self.assertTrue(second["ok"])
        self.assertEqual(second["sent_count"], 0)
        self.assertEqual(sender_b.calls, [])

    def test_state_file_persists_sent_ids(self) -> None:
        self._write_orders([self._accepted_order(client_order_id="tnbuy-state-test")])
        sender = _RecordingSender()
        run_testnet_telegram_alerts(
            testnet_artifacts_dir=self.testnet_dir,
            env=_enabled_env(),
            sender=sender,
            now=self.now,
        )
        state_path = self.testnet_dir / "telegram_testnet_alert_state.json"
        self.assertTrue(state_path.exists())
        state = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertIn("tnbuy-state-test", state["sent_client_order_ids"])

    def test_failed_send_does_not_poison_dedupe_state(self) -> None:
        # First order is sent OK, second fails. The failed one must NOT be
        # added to state, so a future run can retry.
        good = self._accepted_order(client_order_id="tnbuy-ok-1")
        bad = self._accepted_order(client_order_id="tnbuy-bad-2")
        self._write_orders([good, bad])
        sender = _RecordingSender(raises_for={"tnbuy-bad-2"})
        result = run_testnet_telegram_alerts(
            testnet_artifacts_dir=self.testnet_dir,
            env=_enabled_env(),
            sender=sender,
            now=self.now,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["sent_count"], 1)
        self.assertEqual(result["skipped_count"], 1)
        self.assertTrue(any("send_failed" in w for w in result["warnings"]))

        state = json.loads(
            (self.testnet_dir / "telegram_testnet_alert_state.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIn("tnbuy-ok-1", state["sent_client_order_ids"])
        self.assertNotIn("tnbuy-bad-2", state["sent_client_order_ids"])

    def test_failed_send_does_not_leak_token_in_warning(self) -> None:
        bad = self._accepted_order(client_order_id="tnbuy-bad-token-leak")
        self._write_orders([bad])
        sender = _RecordingSender(raises_for={"tnbuy-bad-token-leak"})
        result = run_testnet_telegram_alerts(
            testnet_artifacts_dir=self.testnet_dir,
            env=_enabled_env(),
            sender=sender,
            now=self.now,
        )
        joined = " ".join(result["warnings"])
        self.assertNotIn(_TOKEN, joined)


class DryRunTests(_DispatcherCase):
    def test_dry_run_does_not_invoke_sender_or_state(self) -> None:
        self._write_orders([self._accepted_order(client_order_id="tnbuy-dry")])
        sender = _RecordingSender()
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = run_testnet_telegram_alerts(
                testnet_artifacts_dir=self.testnet_dir,
                env=_enabled_env(),
                sender=sender,
                now=self.now,
                dry_run=True,
            )
        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["sent_count"], 1)
        self.assertEqual(sender.calls, [])
        # State file should NOT be created in dry-run.
        self.assertFalse(
            (self.testnet_dir / "telegram_testnet_alert_state.json").exists()
        )
        out = buf.getvalue()
        self.assertIn("TESTNET", out)
        self.assertIn("TESTNET only", out)


class CredentialResolutionTests(_DispatcherCase):
    def test_missing_token_blocks_send(self) -> None:
        self._write_orders([self._accepted_order()])
        sender = _RecordingSender()
        result = run_testnet_telegram_alerts(
            testnet_artifacts_dir=self.testnet_dir,
            env={ENABLE_FLAG: "1", "TELEGRAM_CHAT_ID": _CHAT_ID},  # no token
            sender=sender,
            now=self.now,
        )
        self.assertFalse(result["ok"])
        self.assertIn("TELEGRAM_BOT_TOKEN", result["reason"])
        self.assertEqual(sender.calls, [])

    def test_chat_id_returned_only_masked(self) -> None:
        self._write_orders([self._accepted_order()])
        sender = _RecordingSender()
        result = run_testnet_telegram_alerts(
            testnet_artifacts_dir=self.testnet_dir,
            env=_enabled_env(),
            sender=sender,
            now=self.now,
        )
        self.assertEqual(result["chat_id_masked"], "*" * (len(_CHAT_ID) - 4) + _CHAT_ID[-4:])
        self.assertNotIn(_CHAT_ID, result.get("chat_id_masked", ""))


class RenderingTests(unittest.TestCase):
    def test_disclaimer_always_present(self) -> None:
        order = {
            "client_order_id": "tn-x",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "type": "MARKET",
            "mode": "order_test",
            "status": "TEST_OK",
            "requested_notional": 25.0,
            "quote_order_qty": 25.0,
        }
        text = render_testnet_order_message(order=order)
        self.assertIn("TESTNET only", text)
        self.assertIn("No live trading", text)

    def test_html_special_chars_in_reason_are_escaped(self) -> None:
        order = {
            "client_order_id": "tn-x",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "type": "MARKET",
            "mode": "order_test",
            "status": "REJECTED",
            "reason": "<script>alert(1)</script>",
            "requested_notional": 25.0,
        }
        text = render_testnet_order_message(order=order)
        self.assertNotIn("<script>", text)
        self.assertIn("&lt;script&gt;", text)


class CLIExitCodeTests(_DispatcherCase):
    def test_main_returns_nonzero_when_disabled_with_reason_in_audit(self) -> None:
        # The CLI uses os.environ; clear the enable flag to simulate the
        # default safe-disabled posture.
        from unittest import mock

        buf = io.StringIO()
        with mock.patch.dict("os.environ", {}, clear=True), redirect_stdout(buf):
            code = main(
                ["--testnet-artifacts-dir", str(self.testnet_dir), "--dry-run"]
            )
        self.assertEqual(code, 1)
        audit = json.loads(buf.getvalue().strip().splitlines()[-1])
        self.assertFalse(audit["ok"])
        self.assertIn("ENABLE_BINANCE_TESTNET_TELEGRAM_ALERTS", audit["reason"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
