import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib import error

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.notifications.telegram_notifier import (
    DEFAULT_BOT_TOKEN_ENV,
    DEFAULT_CHAT_ID_ENV,
    TelegramConfigError,
    TelegramSendError,
    mask_chat_id,
    redact_token,
    resolve_credentials,
    send_telegram_message,
)


class _FakeResponse:
    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self) -> bytes:
        return self._body


class TelegramNotifierTests(unittest.TestCase):
    BOT_TOKEN = "1234567890:AAAA-secret-token-must-not-leak"
    CHAT_ID = "987654321"

    def test_resolve_credentials_uses_env(self) -> None:
        env = {DEFAULT_BOT_TOKEN_ENV: self.BOT_TOKEN, DEFAULT_CHAT_ID_ENV: self.CHAT_ID}
        token, chat = resolve_credentials(env=env)
        self.assertEqual(token, self.BOT_TOKEN)
        self.assertEqual(chat, self.CHAT_ID)

    def test_resolve_credentials_explicit_overrides_env(self) -> None:
        env = {DEFAULT_BOT_TOKEN_ENV: "wrong", DEFAULT_CHAT_ID_ENV: "wrong"}
        token, chat = resolve_credentials(
            bot_token=self.BOT_TOKEN, chat_id=self.CHAT_ID, env=env
        )
        self.assertEqual(token, self.BOT_TOKEN)
        self.assertEqual(chat, self.CHAT_ID)

    def test_resolve_credentials_missing_token_raises(self) -> None:
        with self.assertRaises(TelegramConfigError) as ctx:
            resolve_credentials(env={DEFAULT_CHAT_ID_ENV: self.CHAT_ID})
        self.assertIn(DEFAULT_BOT_TOKEN_ENV, str(ctx.exception))
        self.assertNotIn(self.BOT_TOKEN, str(ctx.exception))

    def test_resolve_credentials_missing_chat_id_raises(self) -> None:
        with self.assertRaises(TelegramConfigError) as ctx:
            resolve_credentials(env={DEFAULT_BOT_TOKEN_ENV: self.BOT_TOKEN})
        self.assertIn(DEFAULT_CHAT_ID_ENV, str(ctx.exception))

    def test_resolve_credentials_blank_token_raises(self) -> None:
        env = {DEFAULT_BOT_TOKEN_ENV: "   ", DEFAULT_CHAT_ID_ENV: self.CHAT_ID}
        with self.assertRaises(TelegramConfigError):
            resolve_credentials(env=env)

    def test_mask_chat_id_redacts_all_but_last_four(self) -> None:
        self.assertEqual(mask_chat_id("987654321"), "*****4321")
        self.assertEqual(mask_chat_id("12"), "**")

    def test_redact_token_replaces_token(self) -> None:
        leak = f"oh no leaked {self.BOT_TOKEN} oops"
        self.assertEqual(redact_token(leak, self.BOT_TOKEN).count(self.BOT_TOKEN), 0)
        self.assertIn("[REDACTED]", redact_token(leak, self.BOT_TOKEN))

    def test_redact_token_handles_url_form(self) -> None:
        url = f"https://api.telegram.org/bot{self.BOT_TOKEN}/sendMessage"
        redacted = redact_token(url, self.BOT_TOKEN)
        self.assertNotIn(self.BOT_TOKEN, redacted)

    def test_send_telegram_message_posts_to_correct_url(self) -> None:
        captured: dict = {}

        def fake_opener(req, timeout):  # noqa: ANN001
            captured["url"] = req.full_url
            captured["data"] = req.data
            captured["timeout"] = timeout
            return _FakeResponse(json.dumps({"ok": True, "result": {"message_id": 7}}).encode("utf-8"))

        result = send_telegram_message(
            bot_token=self.BOT_TOKEN,
            chat_id=self.CHAT_ID,
            text="hello",
            opener=fake_opener,
        )
        self.assertTrue(result["ok"])
        self.assertIn(f"/bot{self.BOT_TOKEN}/sendMessage", captured["url"])
        body = json.loads(captured["data"].decode("utf-8"))
        self.assertEqual(body["chat_id"], self.CHAT_ID)
        self.assertEqual(body["text"], "hello")

    def test_send_failure_response_is_token_redacted(self) -> None:
        def fake_opener(req, timeout):  # noqa: ANN001
            return _FakeResponse(json.dumps({"ok": False, "description": "Bad chat id"}).encode("utf-8"))

        with self.assertRaises(TelegramSendError) as ctx:
            send_telegram_message(
                bot_token=self.BOT_TOKEN,
                chat_id=self.CHAT_ID,
                text="hi",
                opener=fake_opener,
            )
        self.assertNotIn(self.BOT_TOKEN, str(ctx.exception))

    def test_send_http_error_is_token_redacted(self) -> None:
        # The HTTP body itself echoes the token (e.g. server logs the URL into
        # the error envelope). The notifier must redact it from the exception.
        body_with_token = f"Unauthorized: bot{self.BOT_TOKEN}/sendMessage failed".encode("utf-8")

        def fake_opener(req, timeout):  # noqa: ANN001
            raise error.HTTPError(
                url=req.full_url,
                code=401,
                msg="Unauthorized",
                hdrs=None,
                fp=io.BytesIO(body_with_token),
            )

        with self.assertRaises(TelegramSendError) as ctx:
            send_telegram_message(
                bot_token=self.BOT_TOKEN,
                chat_id=self.CHAT_ID,
                text="hi",
                opener=fake_opener,
            )
        self.assertNotIn(self.BOT_TOKEN, str(ctx.exception))
        self.assertIn("[REDACTED]", str(ctx.exception))

    def test_send_url_error_is_token_redacted(self) -> None:
        def fake_opener(req, timeout):  # noqa: ANN001
            raise error.URLError(reason=f"connection failed for token {self.BOT_TOKEN}")

        with self.assertRaises(TelegramSendError) as ctx:
            send_telegram_message(
                bot_token=self.BOT_TOKEN,
                chat_id=self.CHAT_ID,
                text="hi",
                opener=fake_opener,
            )
        self.assertNotIn(self.BOT_TOKEN, str(ctx.exception))

    def test_send_with_empty_token_raises_config_error(self) -> None:
        with self.assertRaises(TelegramConfigError):
            send_telegram_message(bot_token="", chat_id=self.CHAT_ID, text="hi")

    def test_send_with_empty_chat_raises_config_error(self) -> None:
        with self.assertRaises(TelegramConfigError):
            send_telegram_message(bot_token=self.BOT_TOKEN, chat_id="", text="hi")

    def test_send_with_html_parse_mode_includes_field_in_payload(self) -> None:
        captured: dict = {}

        def fake_opener(req, timeout):  # noqa: ANN001
            captured["data"] = req.data
            return _FakeResponse(json.dumps({"ok": True, "result": {}}).encode("utf-8"))

        send_telegram_message(
            bot_token=self.BOT_TOKEN,
            chat_id=self.CHAT_ID,
            text="<b>hi</b>",
            parse_mode="HTML",
            opener=fake_opener,
        )
        body = json.loads(captured["data"].decode("utf-8"))
        self.assertEqual(body["parse_mode"], "HTML")
        self.assertEqual(body["text"], "<b>hi</b>")

    def test_send_without_parse_mode_omits_field(self) -> None:
        captured: dict = {}

        def fake_opener(req, timeout):  # noqa: ANN001
            captured["data"] = req.data
            return _FakeResponse(json.dumps({"ok": True, "result": {}}).encode("utf-8"))

        send_telegram_message(
            bot_token=self.BOT_TOKEN,
            chat_id=self.CHAT_ID,
            text="plain",
            opener=fake_opener,
        )
        body = json.loads(captured["data"].decode("utf-8"))
        self.assertNotIn("parse_mode", body)

    def test_invalid_parse_mode_raises_config_error(self) -> None:
        with self.assertRaises(TelegramConfigError):
            send_telegram_message(
                bot_token=self.BOT_TOKEN,
                chat_id=self.CHAT_ID,
                text="hi",
                parse_mode="HTMLX",
            )


if __name__ == "__main__":
    unittest.main()
