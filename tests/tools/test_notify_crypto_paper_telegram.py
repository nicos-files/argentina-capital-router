import json
import socket
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.notifications.telegram_notifier import (
    DEFAULT_BOT_TOKEN_ENV,
    DEFAULT_CHAT_ID_ENV,
    TelegramSendError,
)
from src.tools.notify_crypto_paper_telegram import (
    ENABLE_FLAG,
    format_event_message,
    notify_crypto_paper_telegram,
)


BOT_TOKEN = "1234567890:AAAA-secret-token-must-not-leak"
CHAT_ID = "987654321"


def _enabled_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        ENABLE_FLAG: "1",
        DEFAULT_BOT_TOKEN_ENV: BOT_TOKEN,
        DEFAULT_CHAT_ID_ENV: CHAT_ID,
    }
    if extra:
        env.update(extra)
    return env


class _RecordingSender:
    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, *, bot_token, chat_id, text, **extra):
        call = {"bot_token": bot_token, "chat_id": chat_id, "text": text}
        call.update(extra)
        self.calls.append(call)
        return {"ok": True}


class NotifyCryptoPaperTelegramTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.artifacts_dir = Path(self._tmp.name) / "crypto_paper"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        (self.artifacts_dir / "evaluation").mkdir(exist_ok=True)
        (self.artifacts_dir / "history").mkdir(exist_ok=True)
        (self.artifacts_dir / "paper_forward").mkdir(exist_ok=True)
        self.now = datetime(2026, 5, 3, 18, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, relative: str, payload) -> None:
        path = self.artifacts_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _seed_take_profit_exit(self) -> None:
        exit_event = {
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
        self._write("crypto_paper_exit_events.json", [exit_event])
        self._write("crypto_paper_snapshot.json", {"equity": 100.64, "positions": []})
        self._write("crypto_paper_positions.json", [])

    def test_refuses_to_send_without_enable_flag(self) -> None:
        self._seed_take_profit_exit()
        sender = _RecordingSender()
        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env={DEFAULT_BOT_TOKEN_ENV: BOT_TOKEN, DEFAULT_CHAT_ID_ENV: CHAT_ID},
            sender=sender,
            now=self.now,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], f"{ENABLE_FLAG}_not_enabled")
        self.assertEqual(sender.calls, [])

    def test_dry_run_does_not_call_network(self) -> None:
        self._seed_take_profit_exit()
        sender = _RecordingSender()

        def _no_network(*args, **kwargs):  # noqa: ANN001
            raise AssertionError("dry-run must not perform network IO")

        with patch("socket.socket", _no_network):
            result = notify_crypto_paper_telegram(
                artifacts_dir=self.artifacts_dir,
                env=_enabled_env(),
                sender=sender,
                dry_run=True,
                now=self.now,
            )
        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(sender.calls, [])
        self.assertEqual(len(result["messages"]), 1)
        self.assertIn("TAKE PROFIT", result["messages"][0])

    def test_missing_token_or_chat_fails_cleanly(self) -> None:
        self._seed_take_profit_exit()
        sender = _RecordingSender()
        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env={ENABLE_FLAG: "1"},
            sender=sender,
            now=self.now,
        )
        self.assertFalse(result["ok"])
        self.assertIn(DEFAULT_BOT_TOKEN_ENV, result["reason"])
        self.assertEqual(sender.calls, [])

    def test_token_is_not_logged_or_returned(self) -> None:
        self._seed_take_profit_exit()
        sender = _RecordingSender()
        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=sender,
            now=self.now,
        )
        encoded = json.dumps({k: v for k, v in result.items() if k != "messages"})
        self.assertNotIn(BOT_TOKEN, encoded)
        # The masked chat_id is allowed; the raw chat_id still must not appear in messages.
        for message in result["messages"]:
            self.assertNotIn(BOT_TOKEN, message)

    def test_sends_only_alertable_events(self) -> None:
        self._seed_take_profit_exit()
        # Add a BUY_SIGNAL via an order; not alertable by default.
        self._write(
            "crypto_paper_orders.json",
            [
                {
                    "order_id": "crypto-paper-order-20260428T150008-0001",
                    "symbol": "BTCUSDT",
                    "side": "BUY",
                    "status": "PENDING",
                    "reason": None,
                    "reference_price": 76000.0,
                    "requested_notional": 25.0,
                    "created_at": "2026-04-28T15:00:08",
                    "metadata": {},
                }
            ],
        )
        sender = _RecordingSender()
        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=sender,
            now=self.now,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(len(sender.calls), 1)
        self.assertIn("TAKE PROFIT", sender.calls[0]["text"])
        for call in sender.calls:
            self.assertNotIn("BUY_SIGNAL", call["text"])

    def test_no_action_is_not_sent_by_default(self) -> None:
        # No artifacts seeded -> only NO_ACTION + WARNING events emitted by semantic layer.
        sender = _RecordingSender()
        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=sender,
            now=self.now,
        )
        self.assertTrue(result["ok"])
        for call in sender.calls:
            self.assertNotIn("NO_ACTION", call["text"])

    def test_dedupe_prevents_duplicate_sends(self) -> None:
        self._seed_take_profit_exit()
        sender = _RecordingSender()
        first = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=sender,
            now=self.now,
        )
        second = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=sender,
            now=self.now,
        )
        self.assertEqual(len(first["sent"]), 1)
        self.assertEqual(len(second["sent"]), 0)
        self.assertEqual(len(second["skipped"]), 1)
        self.assertEqual(second["skipped"][0]["reason"], "already_sent")
        # Sender called exactly once across both runs.
        self.assertEqual(len(sender.calls), 1)

    def test_force_resends_already_sent_events(self) -> None:
        self._seed_take_profit_exit()
        sender = _RecordingSender()
        notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=sender,
            now=self.now,
        )
        self.assertEqual(len(sender.calls), 1)
        forced = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=sender,
            force=True,
            now=self.now,
        )
        self.assertEqual(len(forced["sent"]), 1)
        self.assertEqual(len(sender.calls), 2)

    def test_dry_run_does_not_persist_dedupe_state(self) -> None:
        self._seed_take_profit_exit()
        sender = _RecordingSender()
        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=sender,
            dry_run=True,
            now=self.now,
        )
        state_path = Path(result["state_path"])
        self.assertFalse(state_path.exists())
        # Subsequent non-dry-run must therefore actually send.
        sent = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=sender,
            now=self.now,
        )
        self.assertEqual(len(sent["sent"]), 1)

    def test_min_severity_filters_below_threshold(self) -> None:
        self._seed_take_profit_exit()
        # Add a rejected order (WARNING severity, alertable). With min_severity=ACTION,
        # it must be filtered out.
        self._write(
            "crypto_paper_orders.json",
            [
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
            ],
        )
        sender = _RecordingSender()
        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=sender,
            min_severity="CRITICAL",
            now=self.now,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(sender.calls, [])

    def test_daily_summary_sends_one_summary_message(self) -> None:
        self._seed_take_profit_exit()
        self._write(
            "evaluation/crypto_paper_strategy_metrics.json",
            {
                "closed_trades_count": 3,
                "open_trades_count": 0,
                "win_rate": 1.0,
                "take_profit_count": 3,
                "stop_loss_count": 0,
                "warnings": [],
            },
        )
        sender = _RecordingSender()
        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=sender,
            daily_summary=True,
            now=self.now,
        )
        self.assertTrue(result["ok"])
        # 1 take-profit alert + 1 daily summary
        self.assertEqual(len(sender.calls), 2)
        summary_text = sender.calls[-1]["text"]
        self.assertIn("Crypto Paper Summary", summary_text)
        self.assertIn("Paper-only", summary_text)

    def test_send_failure_is_token_redacted(self) -> None:
        self._seed_take_profit_exit()

        def failing_sender(*, bot_token, chat_id, text):  # noqa: ANN001
            raise TelegramSendError(f"boom token={bot_token}")

        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=failing_sender,
            now=self.now,
        )
        self.assertFalse(result["ok"])
        self.assertNotIn(BOT_TOKEN, result["reason"])

    def test_format_event_message_includes_disclaimer(self) -> None:
        event = {
            "event_id": "x",
            "event_type": "TAKE_PROFIT",
            "severity": "ACTION",
            "symbol": "BTCUSDT",
            "human_title": "Paper TAKE-PROFIT exit: BTCUSDT",
            "human_message": "...",
            "manual_action": "Review.",
            "metadata": {
                "trigger_price": 77131.478,
                "fill_price": 77092.91,
                "realized_pnl": 0.717,
                "entry_average_price": 76286.22,
                "return_pct": 0.0086,
                "stop_loss": 74840.0,
                "take_profit": 77131.478,
                "quote_asset": "USDT",
            },
        }
        text = format_event_message(event)
        # Concise HTML action card with Spanish labels.
        self.assertIn("<b>TAKE PROFIT \u2014 BTCUSDT</b>", text)
        self.assertIn("<b>Entry promedio:</b>", text)
        self.assertIn("<b>Exit paper:</b>", text)
        self.assertIn("<b>P&amp;L realizado:</b>", text)
        self.assertIn("<b>Return:</b>", text)
        self.assertIn("<b>Acci\u00F3n manual:</b>", text)
        self.assertIn("Paper-only", text)
        self.assertIn("No orden real enviada", text)
        # No raw event_type underscore form.
        self.assertNotIn("TAKE_PROFIT", text)
        # No raw JSON dump.
        self.assertNotIn("{", text)
        self.assertNotIn("}", text)

    def test_uses_mocked_http_only(self) -> None:
        # End-to-end network safety: block sockets and rely on injected sender.
        self._seed_take_profit_exit()
        sender = _RecordingSender()

        def _no_network(*args, **kwargs):  # noqa: ANN001
            raise AssertionError("notifier must not open a real socket in tests")

        with patch("socket.socket", _no_network):
            result = notify_crypto_paper_telegram(
                artifacts_dir=self.artifacts_dir,
                env=_enabled_env(),
                sender=sender,
                now=self.now,
            )
        self.assertTrue(result["ok"])
        self.assertEqual(len(sender.calls), 1)


class NotifyCryptoPaperTelegramBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.artifacts_dir = Path(self._tmp.name) / "crypto_paper"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        (self.artifacts_dir / "evaluation").mkdir(exist_ok=True)
        (self.artifacts_dir / "history").mkdir(exist_ok=True)
        (self.artifacts_dir / "paper_forward").mkdir(exist_ok=True)
        self.now = datetime(2026, 5, 3, 18, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _seed_three_alertable_events(self) -> None:
        fill = {
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
        exit_event = {
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
        rejected_order = {
            "order_id": "crypto-paper-order-20260430T230009-0001",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "status": "REJECTED",
            # Non-noisy reason so the default cash_insufficient filter does
            # not drop this row in tests that exercise dedupe behavior.
            "reason": "risk:exposure_limit",
            "reference_price": 76323.24,
            "requested_notional": 25.0,
            "created_at": "2026-04-30T23:00:09",
            "metadata": {},
        }
        (self.artifacts_dir / "crypto_paper_fills.json").write_text(
            json.dumps([fill]), encoding="utf-8"
        )
        (self.artifacts_dir / "crypto_paper_exit_events.json").write_text(
            json.dumps([exit_event]), encoding="utf-8"
        )
        (self.artifacts_dir / "crypto_paper_orders.json").write_text(
            json.dumps([rejected_order]), encoding="utf-8"
        )
        (self.artifacts_dir / "crypto_paper_snapshot.json").write_text(
            json.dumps({"equity": 100.0, "positions": []}), encoding="utf-8"
        )
        (self.artifacts_dir / "crypto_paper_positions.json").write_text(
            "[]", encoding="utf-8"
        )

    def test_bootstrap_writes_state_with_alertable_event_ids(self) -> None:
        self._seed_three_alertable_events()
        sender = _RecordingSender()
        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env={},  # no enable flag, no token, no chat
            sender=sender,
            bootstrap_dedupe=True,
            min_severity="ACTION",
            now=self.now,
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["bootstrap_dedupe"])
        self.assertGreaterEqual(result["marked_count"], 3)
        self.assertEqual(sender.calls, [])

        state_path = Path(result["state_path"])
        self.assertTrue(state_path.exists())
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        self.assertTrue(payload.get("paper_only"))
        self.assertTrue(payload.get("bootstrap_dedupe"))
        ids = set(payload.get("sent_event_ids") or [])
        # Expected alertable events: BUY_FILLED_PAPER, TAKE_PROFIT, ORDER_REJECTED.
        self.assertGreaterEqual(len(ids), 3)

    def test_bootstrap_does_not_call_network(self) -> None:
        self._seed_three_alertable_events()

        def _no_network(*args, **kwargs):  # noqa: ANN001
            raise AssertionError("bootstrap must not perform network IO")

        with patch("socket.socket", _no_network):
            result = notify_crypto_paper_telegram(
                artifacts_dir=self.artifacts_dir,
                env={},
                bootstrap_dedupe=True,
                min_severity="ACTION",
                now=self.now,
            )
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["marked_count"], 3)

    def test_bootstrap_does_not_require_token_or_chat_id(self) -> None:
        self._seed_three_alertable_events()
        # Empty env: no enable flag, no TELEGRAM_BOT_TOKEN, no TELEGRAM_CHAT_ID.
        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env={},
            bootstrap_dedupe=True,
            min_severity="ACTION",
            now=self.now,
        )
        self.assertTrue(result["ok"])
        self.assertIsNone(result["chat_id_masked"])
        self.assertIsNone(result.get("reason"))

    def test_after_bootstrap_normal_notify_skips_old_events(self) -> None:
        self._seed_three_alertable_events()
        bootstrap_result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env={},
            bootstrap_dedupe=True,
            min_severity="ACTION",
            now=self.now,
        )
        self.assertTrue(bootstrap_result["ok"])

        sender = _RecordingSender()
        followup = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=sender,
            min_severity="ACTION",
            now=self.now,
        )
        self.assertTrue(followup["ok"])
        self.assertEqual(sender.calls, [])
        self.assertEqual(len(followup["sent"]), 0)
        self.assertGreaterEqual(len(followup["skipped"]), 3)
        for skip in followup["skipped"]:
            self.assertEqual(skip["reason"], "already_sent")

    def test_force_resends_after_bootstrap(self) -> None:
        self._seed_three_alertable_events()
        notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env={},
            bootstrap_dedupe=True,
            min_severity="ACTION",
            now=self.now,
        )
        sender = _RecordingSender()
        forced = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=sender,
            min_severity="ACTION",
            force=True,
            now=self.now,
        )
        self.assertTrue(forced["ok"])
        self.assertGreaterEqual(len(forced["sent"]), 3)
        self.assertGreaterEqual(len(sender.calls), 3)

    def test_bootstrap_does_not_send_or_print_token(self) -> None:
        self._seed_three_alertable_events()
        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env={DEFAULT_BOT_TOKEN_ENV: BOT_TOKEN, DEFAULT_CHAT_ID_ENV: CHAT_ID},
            bootstrap_dedupe=True,
            min_severity="ACTION",
            now=self.now,
        )
        encoded = json.dumps({k: v for k, v in result.items() if k != "messages"})
        self.assertNotIn(BOT_TOKEN, encoded)
        self.assertNotIn(CHAT_ID, encoded)
        state_path = Path(result["state_path"])
        self.assertNotIn(BOT_TOKEN, state_path.read_text(encoding="utf-8"))


class NotifyCryptoPaperTelegramUXTests(unittest.TestCase):
    """Format/UX/filter behavior tests for the action-card notifier output."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.artifacts_dir = Path(self._tmp.name) / "crypto_paper"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        (self.artifacts_dir / "evaluation").mkdir(exist_ok=True)
        (self.artifacts_dir / "history").mkdir(exist_ok=True)
        (self.artifacts_dir / "paper_forward").mkdir(exist_ok=True)
        self.now = datetime(2026, 5, 3, 18, 0, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_buy_filled_card_uses_concise_html_action_format(self) -> None:
        event = {
            "event_id": "buy:1",
            "event_type": "BUY_FILLED_PAPER",
            "severity": "ACTION",
            "symbol": "BTCUSDT",
            "human_title": "Paper BUY filled BTCUSDT",
            "manual_action": "...",
            "metadata": {
                "fill_price": 76026.524265,
                "gross_notional": 25.0,
                "stop_loss": 74840.444,
                "take_profit": 77131.478,
                "quote_asset": "USDT",
            },
        }
        text = format_event_message(event)
        self.assertIn("\U0001F7E2", text)  # green circle emoji
        self.assertIn("<b>PAPER BUY \u2014 BTCUSDT</b>", text)
        self.assertIn("<b>Acci\u00F3n manual:</b>", text)
        self.assertIn("Revisar compra manual. No ejecutar autom\u00E1tico.", text)
        self.assertIn("<b>Precio ref:</b> 76,026.52", text)
        self.assertIn("<b>Monto paper:</b> 25.00 USDT", text)
        self.assertIn("<b>Stop loss:</b> 74,840.44", text)
        self.assertIn("<b>Take profit:</b> 77,131.48", text)
        self.assertIn("<b>Estado:</b>", text)
        self.assertIn("Paper-only \u00B7 Manual-review", text)
        # Concise: no JSON, no severity tag, no event_type underscore.
        self.assertNotIn("BUY_FILLED_PAPER", text)
        self.assertNotIn("[ACTION]", text)
        self.assertNotIn("{", text)
        self.assertNotIn("}", text)

    def test_take_profit_card_uses_concise_html_action_format(self) -> None:
        event = {
            "event_id": "tp:1",
            "event_type": "TAKE_PROFIT",
            "severity": "ACTION",
            "symbol": "BTCUSDT",
            "human_title": "Paper TAKE-PROFIT exit: BTCUSDT",
            "manual_action": "...",
            "metadata": {
                "trigger_price": 77131.478,
                "fill_price": 77092.91,
                "realized_pnl": 0.64,
                "entry_average_price": 76286.22,
                "return_pct": 0.0086,
                "quote_asset": "USDT",
            },
        }
        text = format_event_message(event)
        self.assertIn("\u2705", text)  # white check mark
        self.assertIn("<b>TAKE PROFIT \u2014 BTCUSDT</b>", text)
        self.assertIn("Si copiaste este trade, revisar toma de ganancia.", text)
        self.assertIn("<b>Entry promedio:</b> 76,286.22", text)
        self.assertIn("<b>Exit paper:</b> 77,092.91", text)
        self.assertIn("<b>P&amp;L realizado:</b> +0.64 USDT", text)
        self.assertIn("<b>Return:</b> +0.86%", text)
        self.assertIn("Paper-only \u00B7 No orden real enviada", text)
        self.assertNotIn("TAKE_PROFIT", text)

    def test_stop_loss_card_uses_concise_html_action_format(self) -> None:
        event = {
            "event_id": "sl:1",
            "event_type": "STOP_LOSS",
            "severity": "ACTION",
            "symbol": "ETHUSDT",
            "human_title": "Paper STOP-LOSS exit: ETHUSDT",
            "manual_action": "...",
            "metadata": {
                "trigger_price": 3000.0,
                "fill_price": 2987.5,
                "realized_pnl": -1.25,
                "entry_average_price": 3050.0,
                "return_pct": -0.0205,
                "quote_asset": "USDT",
            },
        }
        text = format_event_message(event)
        self.assertIn("\U0001F534", text)  # red circle
        self.assertIn("<b>STOP LOSS \u2014 ETHUSDT</b>", text)
        self.assertIn("Si copiaste este trade, revisar cierre o reducci\u00F3n.", text)
        self.assertIn("<b>Entry promedio:</b> 3,050.00", text)
        self.assertIn("<b>Exit paper:</b> 2,987.50", text)
        # Negative PnL must use minus and absolute value.
        self.assertIn("<b>P&amp;L realizado:</b> \u22121.25 USDT", text)
        self.assertIn("<b>Return:</b> \u22122.05%", text)
        self.assertIn("Paper-only \u00B7 No orden real enviada", text)
        self.assertNotIn("STOP_LOSS", text)

    def test_daily_summary_uses_concise_summary_card(self) -> None:
        from src.tools.notify_crypto_paper_telegram import format_daily_summary

        summary = {
            "snapshot": {
                "equity": 100.642,
                "cash": 100.642,
                "realized_pnl": 0.64,
                "unrealized_pnl": 0.0,
            },
            "performance": {
                "closed_trades_count": 3,
                "win_rate": 1.0,
                "take_profit_count": 3,
                "stop_loss_count": 0,
                "total_fees": 0.15,
            },
            "rejected_orders_count": 8,
            "warnings": ["small_sample_size:closed_trades=3_below_min_30"],
        }
        text = format_daily_summary(summary, self.now)
        self.assertIn("\U0001F4CA", text)  # bar chart emoji
        self.assertIn("<b>Crypto Paper Summary</b>", text)
        self.assertIn("<b>Equity:</b> 100.64 USDT", text)
        self.assertIn("<b>P&amp;L realizado:</b> +0.64 USDT", text)
        self.assertIn("<b>Trades cerrados:</b> 3", text)
        self.assertIn("<b>Win rate:</b> 100%", text)
        self.assertIn("<b>Take profits:</b> 3", text)
        self.assertIn("<b>Stop losses:</b> 0", text)
        self.assertIn("<b>Fees:</b> 0.15 USDT", text)
        self.assertIn("\u00D3rdenes rechazadas:</b> 8", text)
        self.assertIn("Muestra chica: menos de 30 trades cerrados.", text)
        self.assertIn("Paper-only \u00B7 Manual-review", text)
        self.assertNotIn("DAILY_SUMMARY", text)
        self.assertNotIn("{", text)

    def test_html_is_escaped_safely(self) -> None:
        # Hostile content in symbol and reason must not break HTML rendering.
        event = {
            "event_id": "x",
            "event_type": "ORDER_REJECTED",
            "severity": "WARNING",
            "symbol": "<script>alert(1)</script>",
            "metadata": {"reason": "bad & evil <tag>"},
        }
        text = format_event_message(event)
        self.assertNotIn("<script>", text)
        self.assertIn("&lt;script&gt;", text)
        self.assertIn("bad &amp; evil &lt;tag&gt;", text)

    def _seed_rejected_only(self, *, reason: str) -> None:
        order = {
            "order_id": f"crypto-paper-order-{reason}",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "status": "REJECTED",
            "reason": reason,
            "reference_price": 76000.0,
            "requested_notional": 25.0,
            "created_at": "2026-04-30T23:00:09",
            "metadata": {},
        }
        (self.artifacts_dir / "crypto_paper_orders.json").write_text(
            json.dumps([order]), encoding="utf-8"
        )
        (self.artifacts_dir / "crypto_paper_snapshot.json").write_text(
            json.dumps({"equity": 100.0, "positions": []}), encoding="utf-8"
        )
        (self.artifacts_dir / "crypto_paper_positions.json").write_text(
            "[]", encoding="utf-8"
        )

    def test_order_rejected_cash_insufficient_is_filtered_by_default(self) -> None:
        self._seed_rejected_only(reason="risk:cash_insufficient")
        sender = _RecordingSender()
        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=sender,
            min_severity="WARNING",
            now=self.now,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(sender.calls, [])
        self.assertEqual(len(result["sent"]), 0)

    def test_order_rejected_other_reasons_are_sent_by_default(self) -> None:
        self._seed_rejected_only(reason="risk:exposure_limit")
        sender = _RecordingSender()
        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=sender,
            min_severity="WARNING",
            now=self.now,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(len(sender.calls), 1)
        self.assertIn("ORDEN RECHAZADA", sender.calls[0]["text"])
        self.assertIn("risk:exposure_limit", sender.calls[0]["text"])

    def test_include_order_rejected_sends_cash_insufficient_too(self) -> None:
        self._seed_rejected_only(reason="risk:cash_insufficient")
        sender = _RecordingSender()
        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=sender,
            min_severity="WARNING",
            include_order_rejected=True,
            now=self.now,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(len(sender.calls), 1)
        self.assertIn("ORDEN RECHAZADA", sender.calls[0]["text"])
        self.assertIn("risk:cash_insufficient", sender.calls[0]["text"])

    def test_default_sender_passes_html_parse_mode(self) -> None:
        # The default sender wraps send_telegram_message with parse_mode=HTML.
        captured: dict[str, Any] = {}

        def _capture_opener(req, timeout=None):  # noqa: ANN001
            captured["url"] = req.full_url
            captured["data"] = req.data

            class _Resp:
                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return False

                def read(self):
                    return b'{"ok": true}'

            return _Resp()

        # Import inside test to avoid leaking module state if patched elsewhere.
        from src.notifications.telegram_notifier import send_telegram_message

        send_telegram_message(
            bot_token=BOT_TOKEN,
            chat_id=CHAT_ID,
            text="<b>hi</b>",
            parse_mode="HTML",
            opener=_capture_opener,
        )
        payload = json.loads(captured["data"].decode("utf-8"))
        self.assertEqual(payload.get("parse_mode"), "HTML")
        self.assertEqual(payload.get("chat_id"), CHAT_ID)
        self.assertEqual(payload.get("text"), "<b>hi</b>")

    def test_messages_do_not_include_raw_metadata_json(self) -> None:
        # A complete dry-run against a TAKE_PROFIT seed yields a card without
        # any JSON metadata leaking into the chat text.
        fill = {
            "fill_id": "f1",
            "order_id": "o1",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": 0.001,
            "fill_price": 76286.22,
            "gross_notional": 76.28622,
            "fee": 0.075,
            "filled_at": "2026-05-03T15:00:00",
            "metadata": {"stop_loss": 74840.0, "take_profit": 77131.478},
        }
        exit_event = {
            "exit_id": "e1",
            "symbol": "BTCUSDT",
            "exit_reason": "TAKE_PROFIT",
            "exit_quantity": 0.001,
            "trigger_price": 77131.478,
            "fill_price": 77092.91,
            "realized_pnl": 0.64,
            "fee": 0.075,
            "exited_at": "2026-05-03T17:45:00",
            "metadata": {"stop_loss": 74840.0, "take_profit": 77131.478},
        }
        (self.artifacts_dir / "crypto_paper_fills.json").write_text(
            json.dumps([fill]), encoding="utf-8"
        )
        (self.artifacts_dir / "crypto_paper_exit_events.json").write_text(
            json.dumps([exit_event]), encoding="utf-8"
        )
        sender = _RecordingSender()
        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=sender,
            now=self.now,
        )
        self.assertTrue(result["ok"])
        for call in sender.calls:
            text = call["text"]
            self.assertNotIn('"event_id"', text)
            self.assertNotIn('"metadata"', text)
            self.assertNotIn("{", text)
            self.assertNotIn("}", text)

    def test_token_is_never_logged_in_messages_or_state(self) -> None:
        self._seed_rejected_only(reason="risk:exposure_limit")
        sender = _RecordingSender()
        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=sender,
            min_severity="WARNING",
            now=self.now,
        )
        encoded = json.dumps({k: v for k, v in result.items() if k != "messages"})
        self.assertNotIn(BOT_TOKEN, encoded)
        for call in sender.calls:
            self.assertNotIn(BOT_TOKEN, call["text"])
        state_path = Path(result["state_path"])
        if state_path.exists():
            self.assertNotIn(BOT_TOKEN, state_path.read_text(encoding="utf-8"))


class NotifyCryptoPaperTelegramDailySummaryOnlyTests(unittest.TestCase):
    """Validate --daily-summary-only behavior and the new audit/state contract."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.artifacts_dir = Path(self._tmp.name) / "crypto_paper"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        (self.artifacts_dir / "evaluation").mkdir(exist_ok=True)
        (self.artifacts_dir / "history").mkdir(exist_ok=True)
        (self.artifacts_dir / "paper_forward").mkdir(exist_ok=True)
        self.now = datetime(2026, 5, 5, 12, 30, 7, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _seed_buy_filled_paper(self) -> dict[str, Any]:
        fill = {
            "fill_id": "f1",
            "order_id": "crypto-paper-order-20260505T123007-0001",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": 0.000327,
            "fill_price": 76286.22,
            "gross_notional": 25.0,
            "fee": 0.075,
            "filled_at": "2026-05-05T12:30:07",
            "metadata": {"stop_loss": 74840.0, "take_profit": 77131.478},
        }
        (self.artifacts_dir / "crypto_paper_fills.json").write_text(
            json.dumps([fill]), encoding="utf-8"
        )
        return fill

    def _enabled(self) -> dict[str, str]:
        return {
            ENABLE_FLAG: "1",
            DEFAULT_BOT_TOKEN_ENV: BOT_TOKEN,
            DEFAULT_CHAT_ID_ENV: CHAT_ID,
        }

    # -- --daily-summary-only ----------------------------------------------

    def test_daily_summary_only_sends_only_summary_and_does_not_mark_pending(self) -> None:
        # Pending BUY_FILLED_PAPER must remain pending so the next 30-minute
        # run still delivers it. The summary itself is sent.
        self._seed_buy_filled_paper()

        class _Recorder:
            def __init__(self) -> None:
                self.calls: list[dict[str, Any]] = []

            def __call__(self, **kwargs: Any) -> dict[str, Any]:
                self.calls.append(kwargs)
                return {"ok": True, "result": {"message_id": 7777}}

        sender = _Recorder()
        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=self._enabled(),
            sender=sender,
            daily_summary_only=True,
            now=self.now,
        )
        self.assertTrue(result["ok"])
        # Exactly ONE Telegram call, the daily summary.
        self.assertEqual(len(sender.calls), 1)
        self.assertIn("Crypto Paper Summary", sender.calls[0]["text"])
        # The pending BUY event must appear in skipped with the dedicated reason.
        skipped_reasons = {s["reason"] for s in result["skipped"]}
        self.assertIn("filtered:daily_summary_only", skipped_reasons)
        # The summary appears in the sent audit; no BUY in sent audit.
        sent_types = {s.get("event_type") for s in result["sent"]}
        self.assertEqual(sent_types, {"DAILY_SUMMARY"})
        # State must NOT mark the BUY event as already-sent.
        state_path = Path(result["state_path"])
        state = json.loads(state_path.read_text(encoding="utf-8"))
        sent_ids = state.get("sent_event_ids") or []
        self.assertFalse(any(_id.startswith("buy:") for _id in sent_ids))

    def test_daily_summary_and_daily_summary_only_are_mutually_exclusive(self) -> None:
        with self.assertRaises(ValueError):
            notify_crypto_paper_telegram(
                artifacts_dir=self.artifacts_dir,
                env=self._enabled(),
                sender=_RecordingSender(),
                daily_summary=True,
                daily_summary_only=True,
                now=self.now,
            )

    def test_normal_notify_sends_new_buy_filled_paper(self) -> None:
        # Default mode (no --daily-summary, no --daily-summary-only) sends
        # new BUY_FILLED_PAPER and DOES NOT send the daily summary.
        self._seed_buy_filled_paper()

        class _Recorder:
            def __init__(self) -> None:
                self.calls: list[dict[str, Any]] = []

            def __call__(self, **kwargs: Any) -> dict[str, Any]:
                self.calls.append(kwargs)
                return {"ok": True, "result": {"message_id": 100 + len(self.calls)}}

        sender = _Recorder()
        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=self._enabled(),
            sender=sender,
            now=self.now,
        )
        self.assertTrue(result["ok"])
        # 1 alert (the BUY) and zero summary messages.
        self.assertEqual(len(sender.calls), 1)
        self.assertIn("PAPER BUY", sender.calls[0]["text"])
        for call in sender.calls:
            self.assertNotIn("Crypto Paper Summary", call["text"])
        # The BUY id is now in sent_event_ids.
        sent_event_ids_audit = result["sent_event_ids"]
        self.assertEqual(len(sent_event_ids_audit), 1)
        self.assertEqual(sent_event_ids_audit[0]["event_type"], "BUY_FILLED_PAPER")
        self.assertEqual(sent_event_ids_audit[0]["delivery_mode"], "sent")
        self.assertEqual(sent_event_ids_audit[0]["telegram_message_id"], 101)

    # -- only-mark-after-ok=true contract ----------------------------------

    def test_send_failure_does_not_mark_event_as_sent(self) -> None:
        self._seed_buy_filled_paper()

        def _failing(**kwargs: Any) -> dict[str, Any]:
            raise TelegramSendError("Telegram send failed: HTTP 500 boom")

        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=self._enabled(),
            sender=_failing,
            now=self.now,
        )
        self.assertFalse(result["ok"])
        # Event must NOT be in the persisted dedupe state.
        state = json.loads(
            Path(result["state_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(state.get("sent_event_ids") or [], [])
        # Event must appear in skipped with a send_failed reason.
        skipped_reasons = {s["reason"] for s in result["skipped"]}
        self.assertIn("send_failed", skipped_reasons)
        # Audit list must reflect the failure too.
        skipped_event_ids = {s["reason"] for s in result["skipped_event_ids"]}
        self.assertIn("send_failed", skipped_event_ids)

    def test_non_ok_response_does_not_mark_event_as_sent(self) -> None:
        # A custom sender returning a dict whose ok is False must be treated
        # exactly like a transport failure: do not add to sent_event_ids.
        self._seed_buy_filled_paper()

        def _ok_false(**kwargs: Any) -> dict[str, Any]:
            return {"ok": False, "description": "Bad chat id"}

        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=self._enabled(),
            sender=_ok_false,
            now=self.now,
        )
        self.assertFalse(result["ok"])
        state = json.loads(
            Path(result["state_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(state.get("sent_event_ids") or [], [])

    def test_telegram_message_id_is_recorded_in_state_when_ok(self) -> None:
        self._seed_buy_filled_paper()

        def _sender(**kwargs: Any) -> dict[str, Any]:
            return {"ok": True, "result": {"message_id": 42}}

        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=self._enabled(),
            sender=_sender,
            now=self.now,
        )
        self.assertTrue(result["ok"])
        state = json.loads(
            Path(result["state_path"]).read_text(encoding="utf-8")
        )
        sent_events = state.get("sent_events") or []
        self.assertEqual(len(sent_events), 1)
        entry = sent_events[0]
        self.assertEqual(entry["delivery_mode"], "sent")
        self.assertEqual(entry["event_type"], "BUY_FILLED_PAPER")
        self.assertEqual(entry["symbol"], "BTCUSDT")
        self.assertEqual(entry["telegram_message_id"], 42)
        self.assertIn("sent_at", entry)

    # -- bootstrap delivery_mode -------------------------------------------

    def test_bootstrap_dedupe_marks_delivery_mode_bootstrap(self) -> None:
        self._seed_buy_filled_paper()
        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env={ENABLE_FLAG: "1"},  # bootstrap does not need credentials
            bootstrap_dedupe=True,
            now=self.now,
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["bootstrap_dedupe"])
        state = json.loads(
            Path(result["state_path"]).read_text(encoding="utf-8")
        )
        sent_events = state.get("sent_events") or []
        self.assertGreaterEqual(len(sent_events), 1)
        modes = {e.get("delivery_mode") for e in sent_events}
        self.assertEqual(modes, {"bootstrap"})
        # Sanity: bootstrap entries do NOT carry a telegram_message_id.
        for entry in sent_events:
            self.assertNotIn("telegram_message_id", entry)

    # -- skipped reasons / audit -------------------------------------------

    def test_already_sent_dedupe_still_prevents_duplicate_send(self) -> None:
        # First run sends; second run with the same artifacts must skip.
        self._seed_buy_filled_paper()

        class _Recorder:
            def __init__(self) -> None:
                self.calls: list[dict[str, Any]] = []

            def __call__(self, **kwargs: Any) -> dict[str, Any]:
                self.calls.append(kwargs)
                return {"ok": True, "result": {"message_id": 1}}

        sender = _Recorder()
        first = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=self._enabled(),
            sender=sender,
            now=self.now,
        )
        self.assertEqual(len(first["sent"]), 1)
        # Second invocation -> sender must not be called again; skip reason
        # must be already_sent.
        sender_after = _Recorder()
        second = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=self._enabled(),
            sender=sender_after,
            now=self.now,
        )
        self.assertTrue(second["ok"])
        self.assertEqual(sender_after.calls, [])
        self.assertEqual(len(second["sent"]), 0)
        skipped_reasons = {s["reason"] for s in second["skipped"]}
        self.assertIn("already_sent", skipped_reasons)

    def test_audit_includes_below_min_severity_reason(self) -> None:
        # Min severity above what the seeded events emit -> all candidates
        # are filtered as below_min_severity (and visible in audit).
        self._seed_buy_filled_paper()
        sender = _RecordingSender()
        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=self._enabled(),
            sender=sender,
            min_severity="CRITICAL",
            now=self.now,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(sender.calls, [])
        skipped_reasons = {s["reason"] for s in result["skipped_event_ids"]}
        self.assertIn("below_min_severity", skipped_reasons)


class NotifyCryptoPaperTelegramSignalOnlyTests(unittest.TestCase):
    """SIGNAL_ONLY routing, opt-in, formatting, dedupe, and visual contract."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.artifacts_dir = Path(self._tmp.name) / "crypto_paper"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        (self.artifacts_dir / "evaluation").mkdir(exist_ok=True)
        (self.artifacts_dir / "history").mkdir(exist_ok=True)
        (self.artifacts_dir / "paper_forward").mkdir(exist_ok=True)
        self.now = datetime(2026, 5, 5, 23, 30, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, relative: str, payload) -> None:
        path = self.artifacts_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def _seed_signal_only(self) -> None:
        """Seed an artifact set with one BUY order that produced no fill."""

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
        self._write("crypto_paper_orders.json", [order])
        self._write(
            "paper_forward/crypto_paper_forward_result.json",
            {
                "recommendations_count": 1,
                "fills_count": 0,
                "exits_count": 0,
                "status": "SUCCESS",
            },
        )
        # Empty fills/snapshot so the only candidates are SIGNAL_ONLY +
        # ORDER_REJECTED. The default cash_insufficient filter on the latter
        # keeps it out of the alert path.
        self._write("crypto_paper_fills.json", [])
        self._write(
            "crypto_paper_snapshot.json", {"equity": 100.0, "positions": []}
        )

    def test_signal_only_is_not_sent_by_default(self) -> None:
        self._seed_signal_only()
        sender = _RecordingSender()
        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=sender,
            now=self.now,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(sender.calls, [])
        self.assertEqual(len(result["sent"]), 0)

    def test_include_signal_only_flag_sends_signal_only(self) -> None:
        self._seed_signal_only()
        sender = _RecordingSender()
        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=sender,
            include_signal_only=True,
            now=self.now,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(len(sender.calls), 1)
        text = sender.calls[0]["text"]
        self.assertIn("SIGNAL ONLY", text)
        self.assertIn("BTCUSDT", text)

    def test_env_enable_crypto_signal_only_alerts_enables_signal_only(self) -> None:
        self._seed_signal_only()
        sender = _RecordingSender()
        env = _enabled_env({"ENABLE_CRYPTO_SIGNAL_ONLY_ALERTS": "1"})
        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=env,
            sender=sender,
            now=self.now,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(len(sender.calls), 1)
        self.assertIn("SIGNAL ONLY", sender.calls[0]["text"])

    def test_signal_only_card_uses_yellow_emoji_and_no_fue_ejecutada_wording(self) -> None:
        self._seed_signal_only()
        sender = _RecordingSender()
        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=sender,
            include_signal_only=True,
            now=self.now,
        )
        self.assertEqual(len(sender.calls), 1)
        text = sender.calls[0]["text"]
        self.assertIn("\U0001F7E1", text)  # yellow circle emoji
        self.assertIn("<b>SIGNAL ONLY \u2014 BTCUSDT</b>", text)
        self.assertIn("Revisar oportunidad. No fue ejecutada en paper.", text)
        self.assertIn("<b>Motivo:</b>", text)
        self.assertIn("risk:cash_insufficient", text)
        self.assertIn("<b>Precio ref:</b> 81,482.11", text)
        self.assertIn("<b>Monto sugerido:</b> 25.00 USDT", text)
        self.assertIn("<b>Stop loss:</b> 79,812.56", text)
        self.assertIn("<b>Take profit:</b> 82,255.80", text)
        self.assertIn("Signal-only \u00B7 Manual-review", text)

    def test_signal_only_card_is_visually_distinct_from_buy_filled_paper(self) -> None:
        # Render both card types side-by-side and check that no SIGNAL_ONLY
        # card can be confused with a PAPER BUY card.
        signal_event = {
            "event_type": "SIGNAL_ONLY",
            "severity": "INFO",
            "symbol": "BTCUSDT",
            "metadata": {
                "reference_price": 81482.11,
                "requested_notional": 25.0,
                "stop_loss": 79812.56,
                "take_profit": 82255.80,
                "rejection_reason": "risk:cash_insufficient",
                "quote_asset": "USDT",
            },
        }
        buy_filled_event = {
            "event_type": "BUY_FILLED_PAPER",
            "severity": "ACTION",
            "symbol": "BTCUSDT",
            "metadata": {
                "fill_price": 76026.52,
                "gross_notional": 25.0,
                "stop_loss": 74840.0,
                "take_profit": 77131.0,
                "quote_asset": "USDT",
            },
        }
        signal_text = format_event_message(signal_event)
        buy_text = format_event_message(buy_filled_event)

        # Distinct emojis.
        self.assertIn("\U0001F7E1", signal_text)  # yellow
        self.assertIn("\U0001F7E2", buy_text)     # green
        self.assertNotIn("\U0001F7E2", signal_text)
        self.assertNotIn("\U0001F7E1", buy_text)
        # Distinct titles.
        self.assertIn("SIGNAL ONLY", signal_text)
        self.assertNotIn("SIGNAL ONLY", buy_text)
        self.assertIn("PAPER BUY", buy_text)
        self.assertNotIn("PAPER BUY", signal_text)
        # SIGNAL_ONLY must NOT claim the order was executed.
        self.assertNotIn("Revisar compra manual", signal_text)
        self.assertIn("No fue ejecutada en paper", signal_text)
        # SIGNAL_ONLY uses the dedicated badge.
        self.assertIn("Signal-only \u00B7 Manual-review", signal_text)
        self.assertNotIn("Signal-only \u00B7 Manual-review", buy_text)

    def test_signal_only_does_not_leak_raw_json_or_token(self) -> None:
        self._seed_signal_only()
        sender = _RecordingSender()
        result = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=sender,
            include_signal_only=True,
            now=self.now,
        )
        self.assertTrue(result["ok"])
        for call in sender.calls:
            text = call["text"]
            self.assertNotIn(BOT_TOKEN, text)
            self.assertNotIn('"event_id"', text)
            self.assertNotIn('"metadata"', text)
            self.assertNotIn("{", text)
            self.assertNotIn("}", text)

    def test_signal_only_html_is_escaped_safely(self) -> None:
        # Hostile content in symbol and reason must not break HTML.
        event = {
            "event_type": "SIGNAL_ONLY",
            "severity": "INFO",
            "symbol": "<script>alert(1)</script>",
            "metadata": {
                "reference_price": 100.0,
                "requested_notional": 25.0,
                "rejection_reason": "bad & evil <tag>",
                "quote_asset": "USDT",
            },
        }
        text = format_event_message(event)
        self.assertNotIn("<script>", text)
        self.assertIn("&lt;script&gt;", text)
        self.assertIn("bad &amp; evil &lt;tag&gt;", text)

    def test_signal_only_is_deduped_across_runs(self) -> None:
        self._seed_signal_only()
        first = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=_RecordingSender(),
            include_signal_only=True,
            now=self.now,
        )
        self.assertEqual(len(first["sent"]), 1)

        second_sender = _RecordingSender()
        second = notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=second_sender,
            include_signal_only=True,
            now=self.now,
        )
        self.assertTrue(second["ok"])
        self.assertEqual(second_sender.calls, [])
        self.assertEqual(len(second["sent"]), 0)
        skip_reasons = {s["reason"] for s in second["skipped"]}
        self.assertIn("already_sent", skip_reasons)

    def test_daily_summary_card_includes_signal_only_count_when_present(self) -> None:
        from src.tools.notify_crypto_paper_telegram import format_daily_summary

        summary = {
            "snapshot": {"equity": 100.0, "realized_pnl": 0.0, "unrealized_pnl": 0.0},
            "performance": {
                "closed_trades_count": 0,
                "win_rate": None,
                "take_profit_count": 0,
                "stop_loss_count": 0,
                "total_fees": 0.0,
            },
            "rejected_orders_count": 0,
            "signal_only_count": 4,
            "warnings": [],
        }
        text = format_daily_summary(summary, self.now)
        self.assertIn("<b>Signals sin ejecutar:</b> 4", text)
        # Zero values should NOT bloat the summary.
        summary_zero = dict(summary, signal_only_count=0)
        text_zero = format_daily_summary(summary_zero, self.now)
        self.assertNotIn("<b>Signals sin ejecutar:</b>", text_zero)


class NotifyCryptoPaperTelegramLocalTzTests(unittest.TestCase):
    """Local-tz line and CRYPTO_LOCAL_TZ env override behavior."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.artifacts_dir = Path(self._tmp.name) / "crypto_paper"
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        (self.artifacts_dir / "evaluation").mkdir(exist_ok=True)
        (self.artifacts_dir / "history").mkdir(exist_ok=True)
        (self.artifacts_dir / "paper_forward").mkdir(exist_ok=True)
        # 23:30 UTC -> 20:30 ART.
        self.now = datetime(2026, 5, 5, 23, 30, tzinfo=timezone.utc)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, relative: str, payload) -> None:
        path = self.artifacts_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def test_local_time_line_is_argentina_by_default(self) -> None:
        # Seed a TAKE_PROFIT that occurred at 23:30 UTC -> 20:30 ART.
        exit_event = {
            "exit_id": "e1",
            "symbol": "BTCUSDT",
            "exit_reason": "TAKE_PROFIT",
            "exit_quantity": 0.001,
            "trigger_price": 77131.478,
            "fill_price": 77092.91,
            "realized_pnl": 0.717,
            "fee": 0.075,
            "exited_at": "2026-05-05T23:30:00",
            "metadata": {"stop_loss": 74840.0, "take_profit": 77131.478},
        }
        self._write("crypto_paper_exit_events.json", [exit_event])
        sender = _RecordingSender()
        notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=sender,
            now=self.now,
        )
        self.assertEqual(len(sender.calls), 1)
        text = sender.calls[0]["text"]
        # The semantic layer's created_at is the moment ``now`` UTC, so the
        # local line on the exit card maps to 20:30 ART for both occurred_at
        # and created_at.
        self.assertIn("Hora local:</b> 20:30 ART", text)
        self.assertIn("UTC:</b> 23:30", text)

    def test_archive_iso_is_not_overridden_by_local_display(self) -> None:
        exit_event = {
            "exit_id": "e1",
            "symbol": "BTCUSDT",
            "exit_reason": "TAKE_PROFIT",
            "exit_quantity": 0.001,
            "trigger_price": 77131.478,
            "fill_price": 77092.91,
            "realized_pnl": 0.717,
            "fee": 0.075,
            "exited_at": "2026-05-05T23:30:00",
            "metadata": {},
        }
        self._write("crypto_paper_exit_events.json", [exit_event])
        # Build the semantic layer once via the notifier path and then
        # re-read the artifact to confirm UTC ISO is preserved.
        notify_crypto_paper_telegram(
            artifacts_dir=self.artifacts_dir,
            env=_enabled_env(),
            sender=_RecordingSender(),
            now=self.now,
        )
        events = json.loads(
            (self.artifacts_dir / "semantic" / "crypto_semantic_events.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(events)
        for event in events:
            self.assertTrue(str(event["created_at"]).endswith("+00:00"))


if __name__ == "__main__":
    unittest.main()
