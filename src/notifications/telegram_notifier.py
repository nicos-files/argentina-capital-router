"""Lightweight Telegram notifier for crypto paper-forward alerts.

Standalone module that:

- reads ``TELEGRAM_BOT_TOKEN`` and ``TELEGRAM_CHAT_ID`` from environment
  variables (or accepts explicit kwargs);
- never logs or returns the raw bot token;
- sends messages via ``https://api.telegram.org/bot<token>/sendMessage`` using
  the standard library only (``urllib``);
- redacts the token from any error message that leaks it.

Paper-only / manual-review only. No live trading, no broker integration, no
auto-execution. The notifier itself sends text only — the callers decide
which messages to send.
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib import error, request

DEFAULT_BOT_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
DEFAULT_CHAT_ID_ENV = "TELEGRAM_CHAT_ID"

_TELEGRAM_API_BASE = "https://api.telegram.org"
_REDACTED = "[REDACTED]"


class TelegramConfigError(ValueError):
    """Raised when bot token / chat id are missing or empty."""


class TelegramSendError(RuntimeError):
    """Raised when sending a Telegram message fails. Always token-redacted."""


def resolve_credentials(
    *,
    bot_token: str | None = None,
    chat_id: str | None = None,
    env: dict[str, str] | None = None,
) -> tuple[str, str]:
    """Resolve and validate the Telegram bot token and chat id.

    Reads from explicit arguments first, then from the environment. Raises
    :class:`TelegramConfigError` with a non-token message when either is
    missing or empty.
    """

    source = env if env is not None else os.environ
    resolved_token = (bot_token if bot_token is not None else source.get(DEFAULT_BOT_TOKEN_ENV)) or ""
    resolved_chat = (chat_id if chat_id is not None else source.get(DEFAULT_CHAT_ID_ENV)) or ""
    resolved_token = resolved_token.strip()
    resolved_chat = resolved_chat.strip()
    if not resolved_token:
        raise TelegramConfigError(
            f"Missing Telegram bot token (set {DEFAULT_BOT_TOKEN_ENV} or pass bot_token=)."
        )
    if not resolved_chat:
        raise TelegramConfigError(
            f"Missing Telegram chat id (set {DEFAULT_CHAT_ID_ENV} or pass chat_id=)."
        )
    return resolved_token, resolved_chat


def mask_chat_id(chat_id: str) -> str:
    text = str(chat_id or "")
    if len(text) <= 4:
        return "*" * len(text)
    return ("*" * (len(text) - 4)) + text[-4:]


def redact_token(text: str, token: str) -> str:
    """Return ``text`` with every occurrence of ``token`` replaced by a marker.

    Defensive against partial leaks: also redacts any ``bot<token>/`` substring
    that might appear in a Telegram URL embedded in an error trace.
    """

    if not token:
        return text
    safe = text.replace(token, _REDACTED)
    safe = safe.replace(f"bot{token}/", f"bot{_REDACTED}/")
    return safe


_ALLOWED_PARSE_MODES = frozenset({"HTML", "Markdown", "MarkdownV2"})


def send_telegram_message(
    *,
    bot_token: str,
    chat_id: str,
    text: str,
    parse_mode: str | None = None,
    timeout_sec: float = 20.0,
    api_base: str = _TELEGRAM_API_BASE,
    opener: Any = None,
) -> dict[str, Any]:
    """Send a Telegram message via the ``sendMessage`` Bot API endpoint.

    Args:
        bot_token: Bot token. Never logged.
        chat_id: Destination chat id (string or int as string).
        text: Message body.
        parse_mode: Optional Telegram parse_mode. One of ``"HTML"``,
            ``"Markdown"``, ``"MarkdownV2"`` or ``None`` (plain text). When
            ``"HTML"`` is used the caller is responsible for HTML-escaping
            user-provided substrings.
        timeout_sec: Network timeout.
        api_base: Override the API base URL (used by tests).
        opener: Optional callable replacing ``urllib.request.urlopen`` for
            testing. Must accept ``(request, timeout=...)`` and return a
            context manager exposing ``read()``.

    Returns:
        Parsed JSON response from Telegram. Always contains ``ok`` boolean.

    Raises:
        TelegramConfigError: when token or chat id is empty, or when
            ``parse_mode`` is not one of the allowed values.
        TelegramSendError: on transport or API errors. Token redacted.
    """

    if not bot_token or not bot_token.strip():
        raise TelegramConfigError("send_telegram_message requires a non-empty bot_token")
    if not chat_id or not str(chat_id).strip():
        raise TelegramConfigError("send_telegram_message requires a non-empty chat_id")
    if parse_mode is not None and parse_mode not in _ALLOWED_PARSE_MODES:
        raise TelegramConfigError(
            f"Invalid parse_mode {parse_mode!r}. Allowed: {sorted(_ALLOWED_PARSE_MODES)} or None."
        )

    url = f"{api_base.rstrip('/')}/bot{bot_token}/sendMessage"
    payload_data: dict[str, Any] = {"chat_id": str(chat_id), "text": str(text)}
    if parse_mode is not None:
        payload_data["parse_mode"] = parse_mode
    payload = json.dumps(payload_data).encode("utf-8")
    req = request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    transport = opener if opener is not None else request.urlopen
    try:
        with transport(req, timeout=timeout_sec) as response:
            body_bytes = response.read()
    except error.HTTPError as exc:
        try:
            body_text = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body_text = ""
        message = redact_token(
            f"Telegram send failed: HTTP {exc.code} {body_text}".strip(),
            bot_token,
        )
        raise TelegramSendError(message) from None
    except error.URLError as exc:
        message = redact_token(f"Telegram send failed: {exc.reason}", bot_token)
        raise TelegramSendError(message) from None
    except Exception as exc:
        message = redact_token(f"Telegram send failed: {exc}", bot_token)
        raise TelegramSendError(message) from None

    try:
        body_text = body_bytes.decode("utf-8")
    except Exception:
        body_text = ""

    try:
        parsed = json.loads(body_text) if body_text else {}
    except Exception:
        message = redact_token(
            f"Telegram returned non-JSON body: {body_text}",
            bot_token,
        )
        raise TelegramSendError(message) from None

    if not isinstance(parsed, dict) or not parsed.get("ok"):
        snippet = redact_token(json.dumps(parsed)[:512], bot_token)
        raise TelegramSendError(f"Telegram send failed: {snippet}")
    return parsed
