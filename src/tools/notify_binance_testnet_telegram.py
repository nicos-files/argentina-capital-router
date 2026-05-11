"""Telegram alert dispatcher for **Binance Spot Testnet** orders.

Reads the testnet executor's artifacts under ``artifacts/crypto_testnet/`` and
sends a short Telegram card per new order. Dedupes by ``client_order_id`` so
re-running the dispatcher never resends an already-announced order.

Hard safety contract:

- Refuses to send unless ``ENABLE_BINANCE_TESTNET_TELEGRAM_ALERTS=1``.
- Reads only testnet artifacts; never inspects live or paper-broker state.
- Every message includes a "TESTNET only \u00b7 No live trading" disclaimer
  and the bot token is never embedded or returned.
- The ``--dry-run`` flag short-circuits the network call.

Paper / testnet only. This module never contacts a broker; it only consumes
artifact files written by the testnet executor.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from src.notifications.telegram_notifier import (
    TelegramConfigError,
    TelegramSendError,
    mask_chat_id,
    redact_token,
    resolve_credentials,
    send_telegram_message,
)


ENABLE_FLAG = "ENABLE_BINANCE_TESTNET_TELEGRAM_ALERTS"
DEFAULT_TESTNET_DIRNAME = "crypto_testnet"
_STATE_FILENAME = "telegram_testnet_alert_state.json"
_ORDERS_FILENAME = "binance_testnet_orders.json"
_RESULT_FILENAME = "binance_testnet_execution_result.json"

_DEFAULT_PARSE_MODE = "HTML"

_TESTNET_DISCLAIMER = "TESTNET only \u00b7 No live trading \u00b7 No mainnet"

_EMOJI_TESTNET = "\U0001F9EA"  # test tube
_EMOJI_BUY = "\U0001F7E2"
_EMOJI_SELL = "\U0001F534"
_EMOJI_REJECTED = "\u26A0\uFE0F"
_EMOJI_TEST_OK = "\u2705"
_EMOJI_PLACED = "\U0001F4E4"  # outbox tray


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Send Telegram alerts for new Binance Spot Testnet orders. "
            f"Refuses unless {ENABLE_FLAG}=1. No live trading."
        )
    )
    parser.add_argument(
        "--testnet-artifacts-dir",
        default=f"artifacts/{DEFAULT_TESTNET_DIRNAME}",
        help=(
            "Binance testnet artifacts root "
            f"(default: artifacts/{DEFAULT_TESTNET_DIRNAME})."
        ),
    )
    parser.add_argument(
        "--state-path",
        default=None,
        help=(
            "Path to the dedupe state JSON. Default: "
            f"<testnet-artifacts-dir>/{_STATE_FILENAME}"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Render messages without contacting Telegram (no dedupe writes).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of new alerts to send per run (default: 20).",
    )
    return parser


def run_testnet_telegram_alerts(
    *,
    testnet_artifacts_dir: str | Path,
    env: Mapping[str, str] | None = None,
    state_path: str | Path | None = None,
    dry_run: bool = False,
    limit: int = 20,
    sender: Any = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Dispatch testnet Telegram alerts.

    Returns a JSON-serializable summary. Never raises on send failure: errors
    are recorded in ``warnings`` and the offending order is left out of the
    state file so a future run can retry.
    """

    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    source: Mapping[str, str] = env if env is not None else os.environ
    testnet_root = Path(testnet_artifacts_dir)
    state_target = (
        Path(state_path) if state_path is not None else testnet_root / _STATE_FILENAME
    )

    base_result: dict[str, Any] = {
        "ok": False,
        "testnet": True,
        "live_trading": False,
        "dry_run": bool(dry_run),
        "considered_count": 0,
        "sent_count": 0,
        "skipped_count": 0,
        "warnings": [],
        "testnet_artifacts_dir": str(testnet_root),
        "state_path": str(state_target),
    }

    if not _is_flag_enabled(source.get(ENABLE_FLAG)):
        base_result["reason"] = (
            f"{ENABLE_FLAG} is not '1'. Testnet Telegram alerts disabled."
        )
        return base_result

    if not testnet_root.exists():
        base_result["reason"] = f"testnet artifacts dir not found: {testnet_root}"
        return base_result

    orders = _load_json_safe(testnet_root / _ORDERS_FILENAME, default=[])
    last_result = _load_json_safe(testnet_root / _RESULT_FILENAME, default={})
    if not isinstance(orders, list):
        orders = []
    if not isinstance(last_result, dict):
        last_result = {}

    actionable_orders: list[Mapping[str, Any]] = [
        order for order in orders if isinstance(order, Mapping)
    ]
    base_result["considered_count"] = len(actionable_orders)

    state = _load_state(state_target)
    seen_ids: set[str] = set(state.get("sent_client_order_ids") or [])

    pending: list[Mapping[str, Any]] = []
    for order in actionable_orders:
        coid = str(order.get("client_order_id") or "")
        if not coid or coid in seen_ids:
            continue
        pending.append(order)
        if len(pending) >= max(0, int(limit)):
            break

    if not pending:
        base_result["ok"] = True
        base_result["reason"] = "no_new_orders"
        return base_result

    # Resolve credentials only when there is at least one message to send.
    if not dry_run:
        try:
            bot_token, chat_id = resolve_credentials(env=dict(source))
        except TelegramConfigError as exc:
            base_result["reason"] = str(exc)
            return base_result
        base_result["chat_id_masked"] = mask_chat_id(chat_id)
    else:
        bot_token = ""
        chat_id = ""
        base_result["chat_id_masked"] = None

    sent: list[str] = []
    skipped: list[dict[str, Any]] = []
    warnings: list[str] = []

    for order in pending:
        coid = str(order.get("client_order_id") or "")
        message_text = render_testnet_order_message(
            order=order, run_metadata=last_result, moment=moment
        )
        if dry_run:
            sys.stdout.write(message_text + "\n\n")
            sent.append(coid)
            continue
        if sender is None:
            send_fn = send_telegram_message
        else:
            send_fn = sender
        try:
            send_fn(
                bot_token=bot_token,
                chat_id=chat_id,
                text=message_text,
                parse_mode=_DEFAULT_PARSE_MODE,
            )
        except TelegramSendError as exc:
            warnings.append(redact_token(f"send_failed:{coid}:{exc}", bot_token))
            skipped.append({"client_order_id": coid, "reason": "send_failed"})
            continue
        except Exception as exc:  # pragma: no cover - defensive
            warnings.append(redact_token(f"unexpected_error:{coid}:{exc}", bot_token))
            skipped.append({"client_order_id": coid, "reason": "unexpected_error"})
            continue
        sent.append(coid)

    if not dry_run and sent:
        seen_ids.update(sent)
        _save_state(
            state_target,
            {
                "sent_client_order_ids": sorted(seen_ids),
                "updated_at": moment.isoformat(),
            },
        )

    base_result.update(
        {
            "ok": True,
            "sent_count": len(sent),
            "skipped_count": len(skipped),
            "warnings": warnings,
            "skipped": skipped,
        }
    )
    return base_result


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_testnet_order_message(
    *,
    order: Mapping[str, Any],
    run_metadata: Mapping[str, Any] | None = None,
    moment: datetime | None = None,
) -> str:
    """Return an HTML Telegram message for a single testnet order.

    Output rules:

    - Always begins with ``\U0001F9EA TESTNET`` and the order kind.
    - Always ends with the ``TESTNET only \u00b7 No live trading`` disclaimer.
    - HTML-escapes every interpolated value.
    """

    status = str(order.get("status") or "").upper()
    mode = str(order.get("mode") or "")
    side = str(order.get("side") or "").upper()
    symbol = str(order.get("symbol") or "")
    coid = str(order.get("client_order_id") or "")
    paper_event_id = str(order.get("paper_event_id") or "")
    paper_event_type = str(order.get("paper_event_type") or "")
    notional = order.get("requested_notional")
    quantity = order.get("quantity")
    quote_qty = order.get("quote_order_qty")
    reason = order.get("reason")
    base_url = (run_metadata or {}).get("base_url") or "n/a"

    if status == "REJECTED":
        title = f"{_EMOJI_TESTNET} TESTNET REJECTED {_EMOJI_REJECTED}"
    elif mode == "order_test" or status == "TEST_OK":
        title = f"{_EMOJI_TESTNET} TESTNET TEST OK {_EMOJI_TEST_OK}"
    else:
        title = f"{_EMOJI_TESTNET} TESTNET PLACED {_EMOJI_PLACED}"

    side_emoji = _EMOJI_BUY if side == "BUY" else (_EMOJI_SELL if side == "SELL" else "")

    lines: list[str] = []
    lines.append(f"<b>{html.escape(title)}</b>")
    lines.append(
        f"{html.escape(side_emoji)} <b>{html.escape(side or 'n/a')}</b> "
        f"<code>{html.escape(symbol or 'n/a')}</code>"
    )
    if quote_qty is not None:
        lines.append(
            f"Quote qty: <code>{html.escape(_format_number(quote_qty))}</code>"
        )
    if quantity is not None:
        lines.append(
            f"Base qty: <code>{html.escape(_format_number(quantity))}</code>"
        )
    if notional is not None:
        lines.append(
            f"Notional: <code>{html.escape(_format_number(notional))}</code>"
        )
    lines.append(f"Status: <code>{html.escape(status or 'n/a')}</code>")
    lines.append(f"Mode: <code>{html.escape(mode or 'n/a')}</code>")
    if reason:
        lines.append(f"Reason: <code>{html.escape(str(reason))}</code>")
    if coid:
        lines.append(f"Client order id: <code>{html.escape(coid)}</code>")
    if paper_event_id:
        lines.append(
            f"Paper event: <code>{html.escape(paper_event_type or '?')}</code> "
            f"(<code>{html.escape(paper_event_id)}</code>)"
        )
    lines.append(f"Base URL: <code>{html.escape(str(base_url))}</code>")
    lines.append(f"<i>{html.escape(_TESTNET_DISCLAIMER)}</i>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_flag_enabled(value: Any) -> bool:
    return str(value or "").strip() == "1"


def _format_number(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return str(value)
    rendered = f"{parsed:,.8f}".rstrip("0").rstrip(".")
    return rendered if rendered else "0"


def _load_json_safe(path: Path, *, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        text = path.read_text(encoding="utf-8").strip()
    except Exception:
        return default
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default


def _load_state(path: Path) -> dict[str, Any]:
    payload = _load_json_safe(path, default=None)
    if not isinstance(payload, dict):
        return {"sent_client_order_ids": []}
    if not isinstance(payload.get("sent_client_order_ids"), list):
        payload["sent_client_order_ids"] = []
    return payload


def _save_state(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_testnet_telegram_alerts(
        testnet_artifacts_dir=args.testnet_artifacts_dir,
        state_path=args.state_path,
        dry_run=bool(args.dry_run),
        limit=int(args.limit),
    )
    audit = {
        "ok": result.get("ok"),
        "testnet": result.get("testnet"),
        "live_trading": result.get("live_trading"),
        "dry_run": result.get("dry_run"),
        "considered_count": result.get("considered_count"),
        "sent_count": result.get("sent_count"),
        "skipped_count": result.get("skipped_count"),
        "chat_id_masked": result.get("chat_id_masked"),
        "reason": result.get("reason"),
        "warnings": result.get("warnings"),
    }
    sys.stdout.write(json.dumps(audit, sort_keys=True) + "\n")
    return 0 if result.get("ok") else 1


__all__ = [
    "ENABLE_FLAG",
    "main",
    "render_testnet_order_message",
    "run_testnet_telegram_alerts",
]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
