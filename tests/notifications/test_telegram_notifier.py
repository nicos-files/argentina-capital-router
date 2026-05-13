import io
import json
import unittest
from contextlib import contextmanager
from unittest import mock

from src.notifications import telegram_notifier as tn
from src.notifications.telegram_notifier import (
    TelegramConfig,
    load_telegram_config,
    send_telegram_message,
)


_FAKE_TOKEN = "123456:FAKE_TOKEN_DO_NOT_USE"
_FAKE_CHAT = "987654321"


@contextmanager
def _fake_urlopen(payload: dict, *, captured: list):
    """Patch ``urllib.request.urlopen`` to capture the outgoing request.

    The fake records (url, body_dict) tuples in ``captured`` and returns the
    given payload as the response body. Importantly, this never makes a real
    network call.
    """

    class _FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()
            return False

    def _fake(request, timeout=10.0):  # type: ignore[override]
        url = request.full_url if hasattr(request, "full_url") else request.get_full_url()
        body = request.data.decode("utf-8") if request.data else "{}"
        captured.append((url, json.loads(body), timeout))
        return _FakeResponse(json.dumps(payload).encode("utf-8"))

    with mock.patch.object(tn.urllib_request, "urlopen", _fake):
        yield


class LoadTelegramConfigTests(unittest.TestCase):
    def test_explicit_args_take_precedence(self) -> None:
        config = load_telegram_config(
            bot_token=_FAKE_TOKEN,
            chat_id=_FAKE_CHAT,
            env={"TELEGRAM_BOT_TOKEN": "ignored", "TELEGRAM_CHAT_ID": "ignored"},
        )
        self.assertEqual(config.bot_token, _FAKE_TOKEN)
        self.assertEqual(config.chat_id, _FAKE_CHAT)

    def test_loads_from_env_mapping(self) -> None:
        config = load_telegram_config(
            env={
                "TELEGRAM_BOT_TOKEN": _FAKE_TOKEN,
                "TELEGRAM_CHAT_ID": _FAKE_CHAT,
            }
        )
        self.assertEqual(config.bot_token, _FAKE_TOKEN)
        self.assertEqual(config.chat_id, _FAKE_CHAT)

    def test_missing_token_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "bot token"):
            load_telegram_config(
                bot_token=None,
                chat_id=_FAKE_CHAT,
                env={"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": _FAKE_CHAT},
            )

    def test_missing_chat_id_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "chat id"):
            load_telegram_config(
                bot_token=_FAKE_TOKEN,
                chat_id=None,
                env={"TELEGRAM_BOT_TOKEN": _FAKE_TOKEN, "TELEGRAM_CHAT_ID": ""},
            )

    def test_missing_error_does_not_leak_token(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            load_telegram_config(
                bot_token=_FAKE_TOKEN, chat_id=None, env={}
            )
        self.assertNotIn(_FAKE_TOKEN, str(ctx.exception))


class SendTelegramMessageDryRunTests(unittest.TestCase):
    def test_dry_run_makes_no_network_call(self) -> None:
        captured: list = []
        config = TelegramConfig(bot_token=_FAKE_TOKEN, chat_id=_FAKE_CHAT)
        with mock.patch.object(
            tn.urllib_request,
            "urlopen",
            side_effect=AssertionError("network call attempted"),
        ):
            result = send_telegram_message(config, "hi", dry_run=True)
        self.assertTrue(result["ok"])
        self.assertTrue(result["dry_run"])
        self.assertFalse(result["sent"])
        self.assertEqual(result["message_preview"], "hi")
        self.assertEqual(result["message_length"], 2)
        self.assertEqual(captured, [])
        # Token must never appear in the dry-run preview payload.
        self.assertNotIn(_FAKE_TOKEN, json.dumps(result))


class SendTelegramMessageRealSendTests(unittest.TestCase):
    def test_successful_send_posts_chat_id_and_text(self) -> None:
        captured: list = []
        config = TelegramConfig(bot_token=_FAKE_TOKEN, chat_id=_FAKE_CHAT)
        with _fake_urlopen({"ok": True, "result": {"message_id": 42}}, captured=captured):
            result = send_telegram_message(config, "hello world")
        self.assertTrue(result["ok"])
        self.assertTrue(result["sent"])
        self.assertFalse(result["dry_run"])
        self.assertEqual(len(captured), 1)
        url, body, _timeout = captured[0]
        self.assertIn("/sendMessage", url)
        self.assertEqual(body["chat_id"], _FAKE_CHAT)
        self.assertEqual(body["text"], "hello world")
        self.assertEqual(body["parse_mode"], "Markdown")
        self.assertTrue(body["disable_web_page_preview"])

    def test_telegram_ok_false_raises_without_token(self) -> None:
        captured: list = []
        config = TelegramConfig(bot_token=_FAKE_TOKEN, chat_id=_FAKE_CHAT)
        with _fake_urlopen(
            {"ok": False, "description": "Bad Request: chat not found"},
            captured=captured,
        ):
            with self.assertRaises(RuntimeError) as ctx:
                send_telegram_message(config, "msg")
        self.assertIn("ok=false", str(ctx.exception))
        self.assertNotIn(_FAKE_TOKEN, str(ctx.exception))

    def test_http_error_redacts_token(self) -> None:
        from urllib.error import HTTPError

        config = TelegramConfig(bot_token=_FAKE_TOKEN, chat_id=_FAKE_CHAT)

        class _BodyReader:
            def read(self):
                return f"Unauthorized for token {_FAKE_TOKEN}".encode("utf-8")

            def close(self):  # pragma: no cover - invoked only at teardown
                return None

        def _raise(*_args, **_kwargs):
            raise HTTPError(
                f"https://api.telegram.org/bot{_FAKE_TOKEN}/sendMessage",
                401,
                "Unauthorized",
                {},
                _BodyReader(),
            )

        with mock.patch.object(tn.urllib_request, "urlopen", side_effect=_raise):
            with self.assertRaises(RuntimeError) as ctx:
                send_telegram_message(config, "msg")
        self.assertNotIn(_FAKE_TOKEN, str(ctx.exception))

    def test_url_error_redacts_token(self) -> None:
        from urllib.error import URLError

        config = TelegramConfig(bot_token=_FAKE_TOKEN, chat_id=_FAKE_CHAT)
        with mock.patch.object(
            tn.urllib_request,
            "urlopen",
            side_effect=URLError(f"unreachable {_FAKE_TOKEN}"),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                send_telegram_message(config, "msg")
        self.assertNotIn(_FAKE_TOKEN, str(ctx.exception))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
