"""Telegram notifier for manual-review-only summaries.

Manual review only. No live trading. No broker automation. No orders.

The notifier is intentionally minimal:

- Configuration is loaded from explicit arguments or environment variables.
  Bot tokens and chat IDs are never read from committed config files.
- A dry-run mode returns a preview without making any network call - this is
  the only path exercised in CI and the default path the rest of the
  codebase takes when running automated tests.
- The real send path uses the standard library (``urllib.request``) so no
  third-party dependency is introduced.
- The bot token is never included in error messages or logs.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping, Optional
from urllib import error as urllib_error
from urllib import request as urllib_request


_TELEGRAM_API_BASE = "https://api.telegram.org"
_ENV_BOT_TOKEN = "TELEGRAM_BOT_TOKEN"
_ENV_CHAT_ID = "TELEGRAM_CHAT_ID"


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    chat_id: str
    parse_mode: str = "Markdown"
    disable_web_page_preview: bool = True


def load_telegram_config(
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
) -> TelegramConfig:
    """Load Telegram credentials from explicit args or environment variables.

    Secrets are only read from CLI arguments or environment variables (never
    from committed config files). Raises ``ValueError`` if either value is
    missing or empty after fallback. The raised message never echoes the
    actual token or chat ID.
    """
    resolved_env: Mapping[str, str] = env if env is not None else os.environ

    token = bot_token if bot_token is not None else resolved_env.get(
        _ENV_BOT_TOKEN, ""
    )
    chat = chat_id if chat_id is not None else resolved_env.get(
        _ENV_CHAT_ID, ""
    )

    token = str(token).strip()
    chat = str(chat).strip()

    if not token:
        raise ValueError(
            "Telegram bot token is required: pass --telegram-bot-token / "
            f"bot_token, or set {_ENV_BOT_TOKEN}."
        )
    if not chat:
        raise ValueError(
            "Telegram chat id is required: pass --telegram-chat-id / "
            f"chat_id, or set {_ENV_CHAT_ID}."
        )
    return TelegramConfig(bot_token=token, chat_id=chat)


def _redact(message: str, secret: str) -> str:
    if not secret:
        return message
    return message.replace(secret, "[REDACTED]")


def _post_json(
    url: str, payload: dict, timeout: float
) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib_request.urlopen(req, timeout=timeout) as response:
        raw = response.read()
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Telegram response was not valid JSON: {exc}"
        ) from exc


def send_telegram_message(
    config: TelegramConfig,
    text: str,
    dry_run: bool = False,
    timeout_seconds: float = 10.0,
) -> dict:
    """Send ``text`` via the Telegram Bot API or return a dry-run preview.

    In dry-run mode no network call is performed. The returned dict in
    dry-run mode intentionally does not contain the bot token or chat id;
    callers can include the chat id separately if they need it.

    On real-send errors (network or non-OK response from Telegram), the bot
    token is redacted from the raised message so that logs/CI output never
    capture the secret.
    """
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "sent": False,
            "message_preview": text,
            "message_length": len(text),
        }

    url = f"{_TELEGRAM_API_BASE}/bot{config.bot_token}/sendMessage"
    payload = {
        "chat_id": config.chat_id,
        "text": text,
        "parse_mode": config.parse_mode,
        "disable_web_page_preview": bool(config.disable_web_page_preview),
    }
    try:
        response = _post_json(url, payload, timeout=timeout_seconds)
    except urllib_error.HTTPError as exc:
        try:
            err_body = exc.read().decode("utf-8", errors="replace")
        except Exception:  # pragma: no cover - defensive
            err_body = ""
        raise RuntimeError(
            _redact(
                f"Telegram HTTP error: {exc.code} {exc.reason} {err_body}".strip(),
                config.bot_token,
            )
        ) from None
    except urllib_error.URLError as exc:
        raise RuntimeError(
            _redact(f"Telegram network error: {exc.reason}", config.bot_token)
        ) from None
    except Exception as exc:  # pragma: no cover - defensive catch-all
        raise RuntimeError(
            _redact(f"Telegram send failed: {exc}", config.bot_token)
        ) from None

    if not isinstance(response, dict) or not response.get("ok"):
        description = ""
        if isinstance(response, dict):
            description = str(response.get("description", "")).strip()
        raise RuntimeError(
            _redact(
                "Telegram API returned ok=false"
                + (f": {description}" if description else ""),
                config.bot_token,
            )
        )

    return {
        "ok": True,
        "dry_run": False,
        "sent": True,
        "message_length": len(text),
        "telegram_response": response,
    }


__all__ = [
    "TelegramConfig",
    "load_telegram_config",
    "send_telegram_message",
]
