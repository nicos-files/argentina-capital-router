"""Telegram alert dispatcher for crypto paper-forward semantic events.

Reads (or rebuilds) the semantic event artifact under
``artifacts/crypto_paper/semantic/`` and sends concise Telegram messages for
the alertable subset only. Maintains a JSON dedupe state so already-sent
events are not resent on subsequent runs.

Refuses to send unless ``ENABLE_CRYPTO_TELEGRAM_ALERTS=1`` is exported.
Supports ``--dry-run`` (prints messages without contacting Telegram),
``--daily-summary`` (also sends a one-line portfolio summary), and
``--force`` (resends previously-sent events). Never logs or returns the bot
token; the resolved chat id is masked.

Paper-only / manual-review only. This tool never executes trades, never
mirrors signals into a live account, and never contacts a broker.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.notifications.telegram_notifier import (
    TelegramConfigError,
    TelegramSendError,
    mask_chat_id,
    redact_token,
    resolve_credentials,
    send_telegram_message,
)
from src.reports.crypto_paper_semantics import (
    ALERTABLE_EVENT_TYPES,
    DEFAULT_CRYPTO_LOCAL_TZ,
    PAPER_DISCLAIMER,
    SEMANTIC_SEVERITIES,
    SIGNAL_ONLY_EVENT_TYPE,
    build_semantic_layer,
    local_display_for_iso,
)


ENABLE_FLAG = "ENABLE_CRYPTO_TELEGRAM_ALERTS"
ENABLE_SIGNAL_ONLY_FLAG = "ENABLE_CRYPTO_SIGNAL_ONLY_ALERTS"
LOCAL_TZ_ENV = "CRYPTO_LOCAL_TZ"

_DEFAULT_MIN_SEVERITY = "ACTION"
_SEVERITY_RANK: dict[str, int] = {name: idx for idx, name in enumerate(SEMANTIC_SEVERITIES)}
_STATE_FILENAME = "telegram_alert_state.json"
_DAILY_SUMMARY_PREFIX = "daily-summary:"

# Default Telegram parse_mode for outbound alert messages.
_DEFAULT_PARSE_MODE = "HTML"

# Reasons that mark an ORDER_REJECTED as routine paper-only noise. By default
# the notifier suppresses these to keep the user's chat actionable; they are
# still counted in the daily summary's rejected_orders metric.
_NOISY_REJECTION_REASON_SUBSTRINGS: tuple[str, ...] = (
    "cash_insufficient",
)

_EMOJI_BY_EVENT_TYPE: dict[str, str] = {
    "BUY_FILLED_PAPER": "\U0001F7E2",  # green circle
    "SIGNAL_ONLY": "\U0001F7E1",        # yellow circle (visually distinct from PAPER BUY)
    "TAKE_PROFIT": "\u2705",            # white heavy check mark
    "STOP_LOSS": "\U0001F534",          # red circle
    "ORDER_REJECTED": "\u26A0\uFE0F",   # warning sign
    "WARNING": "\u26A0\uFE0F",          # warning sign
    "ERROR": "\U0001F6A8",              # rotating police light
    "DAILY_SUMMARY": "\U0001F4CA",      # bar chart
}

_SPANISH_DISCLAIMER_SIGNAL_ONLY = "Signal-only \u00B7 Manual-review"

_SPANISH_DISCLAIMER_PAPER_MANUAL = "Paper-only \u00B7 Manual-review"
_SPANISH_DISCLAIMER_PAPER_NO_REAL = "Paper-only \u00B7 No orden real enviada"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Send concise Telegram alerts for crypto paper-forward semantic events. "
            f"Refuses to send unless {ENABLE_FLAG}=1. Paper-only, manual-review only."
        )
    )
    parser.add_argument(
        "--artifacts-dir",
        default="artifacts/crypto_paper",
        help="Crypto paper artifacts root (default: artifacts/crypto_paper).",
    )
    parser.add_argument(
        "--state-path",
        default=None,
        help=(
            "Path to dedupe state JSON. Default: "
            "<artifacts-dir>/semantic/telegram_alert_state.json"
        ),
    )
    parser.add_argument(
        "--rebuild-semantic",
        action="store_true",
        help="Force rebuild of the semantic layer before alerting.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print messages without contacting Telegram. Skips dedupe writes.",
    )
    summary_group = parser.add_mutually_exclusive_group()
    summary_group.add_argument(
        "--daily-summary",
        action="store_true",
        help=(
            "Send the daily portfolio summary in addition to any pending "
            "alertable events. Kept for backward compatibility; for cron "
            "use, prefer ``--daily-summary-only`` for the once-per-day run."
        ),
    )
    summary_group.add_argument(
        "--daily-summary-only",
        dest="daily_summary_only",
        action="store_true",
        help=(
            "Send ONLY the daily portfolio summary; do not send any per-event "
            "alerts and do not mark BUY_FILLED_PAPER/TAKE_PROFIT/STOP_LOSS "
            "event_ids as already sent. Recommended for the once-per-day cron "
            "entry: it lets the 30-minute cron continue to deliver new "
            "actionable events without being shadowed by the daily summary run."
        ),
    )
    parser.add_argument(
        "--min-severity",
        default=_DEFAULT_MIN_SEVERITY,
        choices=list(SEMANTIC_SEVERITIES),
        help=f"Minimum severity to alert on (default: {_DEFAULT_MIN_SEVERITY}).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Resend events even if their event_id is already in the dedupe state.",
    )
    parser.add_argument(
        "--bootstrap-dedupe",
        "--mark-existing-sent",
        dest="bootstrap_dedupe",
        action="store_true",
        help=(
            "Read current semantic events and mark every alertable event_id "
            "as already sent in the dedupe state. Does not contact Telegram. "
            "Does not require TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID. Useful "
            "the first time the notifier is wired up against a populated "
            "artifacts directory, to avoid replaying historical alerts."
        ),
    )
    parser.add_argument(
        "--include-order-rejected",
        dest="include_order_rejected",
        action="store_true",
        help=(
            "Send all ORDER_REJECTED events. By default, rejected orders "
            "whose reason matches a routine pattern (e.g. cash_insufficient) "
            "are suppressed to reduce noise; they are still counted in the "
            "daily summary's rejected_orders metric."
        ),
    )
    parser.add_argument(
        "--include-signal-only",
        dest="include_signal_only",
        action="store_true",
        help=(
            "Send SIGNAL_ONLY events as concise yellow action cards. "
            "SIGNAL_ONLY represents 'BUY opportunity detected, paper "
            "execution did not open a position' (e.g. recommendations_count=1 "
            "with fills_count=0). Off by default to avoid noise. The env "
            f"{ENABLE_SIGNAL_ONLY_FLAG}=1 enables it without --include-signal-only."
        ),
    )
    parser.add_argument(
        "--local-tz",
        dest="local_tz",
        default=None,
        help=(
            "Local timezone used for the 'Hora local' line in alert cards. "
            f"Defaults to env {LOCAL_TZ_ENV} or {DEFAULT_CRYPTO_LOCAL_TZ}. "
            "UTC archive ids are not affected."
        ),
    )
    return parser


def notify_crypto_paper_telegram(
    *,
    artifacts_dir: str | Path,
    state_path: str | Path | None = None,
    dry_run: bool = False,
    daily_summary: bool = False,
    daily_summary_only: bool = False,
    min_severity: str = _DEFAULT_MIN_SEVERITY,
    force: bool = False,
    rebuild_semantic: bool = False,
    bootstrap_dedupe: bool = False,
    include_order_rejected: bool = False,
    include_signal_only: bool = False,
    local_tz: str | None = None,
    env: dict[str, str] | None = None,
    sender: Any = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Dispatch Telegram alerts for the latest crypto paper semantic events.

    Args:
        artifacts_dir: Crypto paper artifacts root directory.
        state_path: Override path for the dedupe state JSON.
        dry_run: When True, do not contact Telegram and do not write state.
        daily_summary: When True, also send a portfolio summary message.
        min_severity: Minimum severity to alert on.
        force: When True, ignore dedupe state and resend all alertable events.
        rebuild_semantic: When True, rebuild the semantic layer first.
        bootstrap_dedupe: When True, mark every current alertable event_id as
            already sent without contacting Telegram and without requiring
            ``TELEGRAM_BOT_TOKEN`` or ``TELEGRAM_CHAT_ID``. Mutually compatible
            with ``min_severity``; mutually exclusive with sending. Always
            persists the dedupe state.
        env: Optional environment-variable map for tests.
        sender: Optional callable replacing the Telegram sender for tests.
            Signature: ``sender(bot_token, chat_id, text) -> dict``.
        now: Optional clock override for the daily-summary timestamp.

    Returns:
        Dict with ``sent``, ``skipped``, ``messages`` (text only), ``state_path``,
        ``dry_run``, ``bootstrap_dedupe``, ``marked_count``, ``paper_only``,
        ``live_trading``, and a token-redacted ``chat_id_masked``.
    """

    if min_severity not in _SEVERITY_RANK:
        raise ValueError(f"Invalid min_severity: {min_severity!r}")
    if daily_summary and daily_summary_only:
        raise ValueError(
            "daily_summary and daily_summary_only are mutually exclusive"
        )

    source_env = env if env is not None else os.environ

    # Resolve include_signal_only via CLI/explicit kwarg or env opt-in.
    if not include_signal_only and str(
        source_env.get(ENABLE_SIGNAL_ONLY_FLAG) or ""
    ).strip() == "1":
        include_signal_only = True

    resolved_local_tz = (
        str(local_tz).strip()
        if local_tz
        else str(source_env.get(LOCAL_TZ_ENV) or DEFAULT_CRYPTO_LOCAL_TZ)
    )

    artifacts_root = Path(artifacts_dir)
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    semantic_dir = artifacts_root / "semantic"
    semantic_dir.mkdir(parents=True, exist_ok=True)
    resolved_state_path = (
        Path(state_path) if state_path is not None else semantic_dir / _STATE_FILENAME
    )

    # The ENABLE_CRYPTO_TELEGRAM_ALERTS gate guards real network sends only.
    # Dry-run and bootstrap-dedupe never contact Telegram, so they bypass it.
    enabled = str(source_env.get(ENABLE_FLAG) or "").strip()
    if enabled != "1" and not dry_run and not bootstrap_dedupe:
        return {
            "ok": False,
            "paper_only": True,
            "live_trading": False,
            "sent": [],
            "skipped": [],
            "messages": [],
            "dry_run": bool(dry_run),
            "bootstrap_dedupe": bool(bootstrap_dedupe),
            "marked_count": 0,
            "reason": f"{ENABLE_FLAG}_not_enabled",
            "chat_id_masked": None,
            "state_path": None,
        }

    semantic_layer = _load_or_build_semantic_layer(
        artifacts_root=artifacts_root,
        rebuild=rebuild_semantic,
        moment=moment,
    )
    events = list(semantic_layer.get("events") or [])

    threshold = _SEVERITY_RANK[min_severity]
    # SIGNAL_ONLY is only alertable when the user opts in. When opted in, we
    # bypass the global min_severity threshold for this type so the default
    # ACTION threshold does not silently drop INFO-severity SIGNAL_ONLY events.
    effective_alertable_types: set[str] = set(ALERTABLE_EVENT_TYPES)
    if include_signal_only:
        effective_alertable_types.add(SIGNAL_ONLY_EVENT_TYPE)
    candidates: list[dict[str, Any]] = []
    pre_filtered: list[dict[str, Any]] = []  # observability for skipped reasons.
    for event in events:
        event_type = str(event.get("event_type") or "")
        severity = str(event.get("severity") or "INFO")
        event_id = str(event.get("event_id") or "")
        if event_type not in effective_alertable_types:
            # Non-alertable events (e.g. NO_ACTION, BUY_SIGNAL, and SIGNAL_ONLY
            # when --include-signal-only is off) are not surfaced in skipped
            # to avoid drowning the audit log.
            continue
        # Per-type bypass: SIGNAL_ONLY events skip the min_severity gate when
        # explicitly opted in. All other types still go through the gate.
        if (
            event_type != SIGNAL_ONLY_EVENT_TYPE
            and _SEVERITY_RANK.get(severity, -1) < threshold
        ):
            pre_filtered.append({"event_id": event_id, "reason": "below_min_severity"})
            continue
        if event_type == "ORDER_REJECTED" and not include_order_rejected:
            reason_text = str((event.get("metadata") or {}).get("reason") or "").lower()
            if any(noise in reason_text for noise in _NOISY_REJECTION_REASON_SUBSTRINGS):
                pre_filtered.append(
                    {"event_id": event_id, "reason": "noisy_order_rejected"}
                )
                continue
        candidates.append(event)

    state = _load_state(resolved_state_path)
    sent_ids: set[str] = set(state.get("sent_event_ids") or [])
    sent_payload: list[dict[str, Any]] = []
    skipped_payload: list[dict[str, Any]] = []
    messages: list[str] = []

    sent_events_meta: list[dict[str, Any]] = list(state.get("sent_events") or [])

    if bootstrap_dedupe:
        before = len(sent_ids)
        bootstrap_now_iso = moment.isoformat()
        existing_meta_ids = {str(e.get("event_id") or "") for e in sent_events_meta}
        for event in candidates:
            event_id = str(event.get("event_id") or "")
            if not event_id:
                continue
            if event_id not in sent_ids:
                sent_ids.add(event_id)
            if event_id not in existing_meta_ids:
                sent_events_meta.append(
                    {
                        "event_id": event_id,
                        "event_type": str(event.get("event_type") or ""),
                        "symbol": str(event.get("symbol") or ""),
                        "sent_at": bootstrap_now_iso,
                        "delivery_mode": "bootstrap",
                    }
                )
                existing_meta_ids.add(event_id)
        marked_count = len(sent_ids) - before
        _save_state(
            resolved_state_path,
            {
                "sent_event_ids": sorted(sent_ids),
                "sent_events": sent_events_meta,
                "last_updated_at": bootstrap_now_iso,
                "paper_only": True,
                "bootstrap_dedupe": True,
            },
        )
        return {
            "ok": True,
            "paper_only": True,
            "live_trading": False,
            "sent": [],
            "skipped": [],
            "sent_event_ids": [],
            "skipped_event_ids": [],
            "messages": [],
            "dry_run": False,
            "bootstrap_dedupe": True,
            "marked_count": int(marked_count),
            "considered_count": len(candidates),
            "chat_id_masked": None,
            "state_path": str(resolved_state_path),
            "min_severity": min_severity,
        }

    # Carry pre-filter skipped entries (severity / noisy rejected) into the
    # public skipped audit so callers can see why each event_id was dropped.
    skipped_payload.extend(pre_filtered)

    # ``daily_summary_only`` short-circuits the per-event send loop entirely:
    # every candidate is recorded as ``filtered:daily_summary_only`` in the
    # skipped audit and is NOT added to ``sent_event_ids``. This guarantees
    # the daily cron run cannot shadow pending BUY/TAKE/STOP alerts.
    will_send_summary = bool(daily_summary or daily_summary_only)
    iter_candidates = [] if daily_summary_only else candidates
    if daily_summary_only:
        for event in candidates:
            skipped_payload.append(
                {
                    "event_id": str(event.get("event_id") or ""),
                    "reason": "filtered:daily_summary_only",
                }
            )

    bot_token: str | None = None
    chat_id: str | None = None
    chat_id_masked: str | None = None
    if not dry_run and (iter_candidates or will_send_summary):
        try:
            bot_token, chat_id = resolve_credentials(env=source_env)
        except TelegramConfigError as exc:
            return {
                "ok": False,
                "paper_only": True,
                "live_trading": False,
                "sent": [],
                "skipped": skipped_payload,
                "sent_event_ids": [],
                "skipped_event_ids": [
                    {"event_id": s["event_id"], "reason": s["reason"]}
                    for s in skipped_payload
                ],
                "messages": [],
                "dry_run": False,
                "reason": str(exc),
                "chat_id_masked": None,
                "state_path": str(resolved_state_path),
            }
        chat_id_masked = mask_chat_id(chat_id)

    transport = sender if sender is not None else _default_sender

    failure_reason: str | None = None
    moment_iso = moment.isoformat()

    def _record_sent(
        *,
        event_id: str,
        event_type: str,
        symbol: str,
        delivery_mode: str,
        telegram_message_id: Any = None,
    ) -> None:
        """Append a sent_events metadata entry and update the dedupe set.

        Only invoked AFTER Telegram has returned ok=true (or in dry-run /
        bootstrap modes that explicitly never contact the network).
        """
        entry: dict[str, Any] = {
            "event_id": event_id,
            "event_type": event_type,
            "symbol": symbol,
            "sent_at": moment_iso,
            "delivery_mode": delivery_mode,
        }
        if telegram_message_id is not None:
            entry["telegram_message_id"] = telegram_message_id
        sent_events_meta.append(entry)
        if delivery_mode == "sent":
            sent_ids.add(event_id)

    for event in iter_candidates:
        event_id = str(event.get("event_id") or "")
        event_type = str(event.get("event_type") or "")
        symbol = str(event.get("symbol") or "")
        if not force and event_id in sent_ids:
            skipped_payload.append({"event_id": event_id, "reason": "already_sent"})
            continue
        text = format_event_message(event, local_tz=resolved_local_tz)
        messages.append(text)
        if dry_run:
            sent_payload.append(
                {
                    "event_id": event_id,
                    "event_type": event_type,
                    "symbol": symbol,
                    "delivery_mode": "dry_run_skipped",
                }
            )
            continue
        try:
            response = transport(
                bot_token=bot_token or "", chat_id=chat_id or "", text=text
            )
        except TelegramSendError as exc:
            failure_reason = redact_token(str(exc), bot_token or "")
            skipped_payload.append(
                {"event_id": event_id, "reason": f"send_failed"}
            )
            break
        # Defensive: only mark sent when the API explicitly returns ok=true.
        # send_telegram_message already raises on ok=false, but a custom
        # sender (tests or future implementations) might return a dict whose
        # ok is missing or false. Refuse to mark in that case.
        if not isinstance(response, dict) or not response.get("ok"):
            failure_reason = "send_failed:non_ok_response"
            skipped_payload.append(
                {"event_id": event_id, "reason": "send_failed"}
            )
            break
        message_id = (response.get("result") or {}).get("message_id")
        sent_payload.append(
            {
                "event_id": event_id,
                "event_type": event_type,
                "symbol": symbol,
                "delivery_mode": "sent",
                "telegram_message_id": message_id,
            }
        )
        _record_sent(
            event_id=event_id,
            event_type=event_type,
            symbol=symbol,
            delivery_mode="sent",
            telegram_message_id=message_id,
        )

    if will_send_summary and failure_reason is None:
        summary_payload = semantic_layer.get("summary") or {}
        text = format_daily_summary(
            summary_payload, moment, local_tz=resolved_local_tz
        )
        summary_event_id = f"{_DAILY_SUMMARY_PREFIX}{moment.strftime('%Y-%m-%d')}"
        if not force and summary_event_id in sent_ids:
            skipped_payload.append(
                {"event_id": summary_event_id, "reason": "already_sent"}
            )
        else:
            messages.append(text)
            if dry_run:
                sent_payload.append(
                    {
                        "event_id": summary_event_id,
                        "event_type": "DAILY_SUMMARY",
                        "symbol": "",
                        "delivery_mode": "dry_run_skipped",
                    }
                )
            else:
                try:
                    response = transport(
                        bot_token=bot_token or "",
                        chat_id=chat_id or "",
                        text=text,
                    )
                except TelegramSendError as exc:
                    failure_reason = redact_token(str(exc), bot_token or "")
                    skipped_payload.append(
                        {
                            "event_id": summary_event_id,
                            "reason": "send_failed",
                        }
                    )
                else:
                    if not isinstance(response, dict) or not response.get("ok"):
                        failure_reason = "send_failed:non_ok_response"
                        skipped_payload.append(
                            {
                                "event_id": summary_event_id,
                                "reason": "send_failed",
                            }
                        )
                    else:
                        message_id = (response.get("result") or {}).get("message_id")
                        sent_payload.append(
                            {
                                "event_id": summary_event_id,
                                "event_type": "DAILY_SUMMARY",
                                "symbol": "",
                                "delivery_mode": "sent",
                                "telegram_message_id": message_id,
                            }
                        )
                        _record_sent(
                            event_id=summary_event_id,
                            event_type="DAILY_SUMMARY",
                            symbol="",
                            delivery_mode="sent",
                            telegram_message_id=message_id,
                        )

    # Persist whatever was actually delivered. In dry-run we do not write
    # state at all (matches the historic contract). In real-send mode we
    # always persist the partial state, even when a later send failed: that
    # way already-delivered events are correctly recorded as sent.
    if not dry_run:
        _save_state(
            resolved_state_path,
            {
                "sent_event_ids": sorted(sent_ids),
                "sent_events": sent_events_meta,
                "last_updated_at": moment_iso,
                "paper_only": True,
            },
        )

    skipped_event_ids = [
        {"event_id": s["event_id"], "reason": s["reason"]}
        for s in skipped_payload
    ]
    sent_event_ids_audit = [
        {
            "event_id": s["event_id"],
            "event_type": s.get("event_type"),
            "symbol": s.get("symbol"),
            "delivery_mode": s.get("delivery_mode"),
            "telegram_message_id": s.get("telegram_message_id"),
        }
        for s in sent_payload
    ]

    result: dict[str, Any] = {
        "ok": failure_reason is None,
        "paper_only": True,
        "live_trading": False,
        "sent": sent_payload,
        "skipped": skipped_payload,
        "sent_event_ids": sent_event_ids_audit,
        "skipped_event_ids": skipped_event_ids,
        "messages": messages,
        "dry_run": bool(dry_run),
        "daily_summary_only": bool(daily_summary_only),
        "bootstrap_dedupe": False,
        "include_signal_only": bool(include_signal_only),
        "local_tz": resolved_local_tz,
        "marked_count": 0,
        "chat_id_masked": chat_id_masked,
        "state_path": str(resolved_state_path),
        "min_severity": min_severity,
    }
    if failure_reason is not None:
        result["reason"] = failure_reason
    return result


def format_event_message(
    event: dict[str, Any], *, local_tz: str | None = None
) -> str:
    """Render an event as a concise HTML action card for Telegram.

    The output is suitable for ``parse_mode="HTML"``. All user-derived
    substrings (symbol, reason) are HTML-escaped. The card is intentionally
    short and mobile-friendly. No raw JSON, no severity tag, no event_type
    suffixed with underscores. When ``local_tz`` is provided, a 'Hora local'
    / 'UTC' time line is appended; the underlying UTC archive id is unaffected.
    """

    event_type = str(event.get("event_type") or "")
    symbol = str(event.get("symbol") or "")
    metadata = event.get("metadata") or {}
    quote = _quote_label(metadata.get("quote_asset"))
    tz_name = str(local_tz or DEFAULT_CRYPTO_LOCAL_TZ)
    time_lines = _build_time_lines(event=event, tz_name=tz_name)

    if event_type == "BUY_FILLED_PAPER":
        return _format_buy_filled_card(
            symbol=symbol, metadata=metadata, quote=quote, time_lines=time_lines
        )
    if event_type == "SIGNAL_ONLY":
        return _format_signal_only_card(
            symbol=symbol, metadata=metadata, quote=quote, time_lines=time_lines
        )
    if event_type == "TAKE_PROFIT":
        return _format_exit_card(
            symbol=symbol,
            metadata=metadata,
            quote=quote,
            emoji=_EMOJI_BY_EVENT_TYPE["TAKE_PROFIT"],
            title="TAKE PROFIT",
            manual_action_es="Si copiaste este trade, revisar toma de ganancia.",
            time_lines=time_lines,
        )
    if event_type == "STOP_LOSS":
        return _format_exit_card(
            symbol=symbol,
            metadata=metadata,
            quote=quote,
            emoji=_EMOJI_BY_EVENT_TYPE["STOP_LOSS"],
            title="STOP LOSS",
            manual_action_es="Si copiaste este trade, revisar cierre o reducci\u00F3n.",
            time_lines=time_lines,
        )
    if event_type == "ORDER_REJECTED":
        return _format_order_rejected_card(
            symbol=symbol, metadata=metadata, time_lines=time_lines
        )
    if event_type == "ERROR":
        return _format_error_card(event=event, time_lines=time_lines)
    if event_type == "WARNING":
        return _format_warning_card(event=event, time_lines=time_lines)
    # Fallback: minimal card from the human title + manual action.
    return _format_generic_card(event=event, time_lines=time_lines)


def format_daily_summary(
    summary: dict[str, Any], moment: datetime, *, local_tz: str | None = None
) -> str:
    """Render the daily portfolio summary as a concise HTML card."""

    snapshot = summary.get("snapshot") or {}
    performance = summary.get("performance") or {}
    quote = _quote_label((snapshot.get("quote_asset") if isinstance(snapshot, dict) else None) or "USDT")
    rejected_count = summary.get("rejected_orders_count")
    signal_only_count = summary.get("signal_only_count")
    tz_name = str(local_tz or DEFAULT_CRYPTO_LOCAL_TZ)

    lines: list[str] = []
    lines.append(f"{_EMOJI_BY_EVENT_TYPE['DAILY_SUMMARY']} <b>Crypto Paper Summary</b>")
    lines.append("")
    lines.append(f"<b>Equity:</b> {_fmt_amount(snapshot.get('equity'))} {quote}")
    lines.append(
        f"<b>P&amp;L realizado:</b> {_fmt_signed_amount(snapshot.get('realized_pnl'))} {quote}"
    )
    lines.append(f"<b>Trades cerrados:</b> {_fmt_int(performance.get('closed_trades_count'))}")
    lines.append(f"<b>Win rate:</b> {_fmt_pct_int(performance.get('win_rate'))}")
    lines.append(f"<b>Take profits:</b> {_fmt_int(performance.get('take_profit_count'))}")
    lines.append(f"<b>Stop losses:</b> {_fmt_int(performance.get('stop_loss_count'))}")
    lines.append(f"<b>Fees:</b> {_fmt_amount(performance.get('total_fees'))} {quote}")
    if rejected_count is not None and int(rejected_count or 0) > 0:
        lines.append(f"<b>\u00D3rdenes rechazadas:</b> {_fmt_int(rejected_count)}")
    if signal_only_count is not None and int(signal_only_count or 0) > 0:
        lines.append(
            f"<b>Signals sin ejecutar:</b> {_fmt_int(signal_only_count)}"
        )

    small_sample = _small_sample_warning(summary)
    if small_sample:
        lines.append("")
        lines.append(
            f"{_EMOJI_BY_EVENT_TYPE['WARNING']} "
            f"Muestra chica: menos de 30 trades cerrados."
        )
    # Local-time line (UTC archive ids unaffected).
    local = local_display_for_iso(moment.isoformat(), tz_name=tz_name)
    if local is not None:
        lines.append("")
        lines.append(
            f"<b>Hora local:</b> {local['time_local']} {local['tz_label']}"
        )
        lines.append(f"<b>UTC:</b> {local['time_utc']}")
    lines.append("")
    lines.append(f"<b>Estado:</b>")
    lines.append(_SPANISH_DISCLAIMER_PAPER_MANUAL)
    return "\n".join(lines)


# --- Action-card renderers --------------------------------------------------


def _format_buy_filled_card(
    *,
    symbol: str,
    metadata: dict[str, Any],
    quote: str,
    time_lines: list[str] | None = None,
) -> str:
    title = f"PAPER BUY \u2014 {html.escape(symbol)}"
    fill_price = metadata.get("fill_price")
    gross_notional = metadata.get("gross_notional")
    sl = metadata.get("stop_loss")
    tp = metadata.get("take_profit")
    lines = [
        f"{_EMOJI_BY_EVENT_TYPE['BUY_FILLED_PAPER']} <b>{title}</b>",
        "",
        "<b>Acci\u00F3n manual:</b>",
        "Revisar compra manual. No ejecutar autom\u00E1tico.",
        "",
        f"<b>Precio ref:</b> {_fmt_price(fill_price)}",
        f"<b>Monto paper:</b> {_fmt_amount(gross_notional)} {quote}",
    ]
    if sl is not None:
        lines.append(f"<b>Stop loss:</b> {_fmt_price(sl)}")
    if tp is not None:
        lines.append(f"<b>Take profit:</b> {_fmt_price(tp)}")
    if time_lines:
        lines.append("")
        lines.extend(time_lines)
    lines.append("")
    lines.append("<b>Estado:</b>")
    lines.append(_SPANISH_DISCLAIMER_PAPER_MANUAL)
    return "\n".join(lines)


def _format_signal_only_card(
    *,
    symbol: str,
    metadata: dict[str, Any],
    quote: str,
    time_lines: list[str] | None = None,
) -> str:
    """Render a SIGNAL_ONLY event as a yellow action card.

    Visually distinct from PAPER BUY: yellow circle, explicit 'No fue
    ejecutada en paper' wording, and the 'Signal-only \u00B7 Manual-review'
    badge. Reason / stop / take fields are included only when present in
    metadata; nothing is invented.
    """

    title = f"SIGNAL ONLY \u2014 {html.escape(symbol)}"
    reference_price = metadata.get("reference_price")
    requested_notional = metadata.get("requested_notional")
    sl = metadata.get("stop_loss")
    tp = metadata.get("take_profit")
    raw_reason = metadata.get("rejection_reason") or metadata.get("reason")
    lines: list[str] = [
        f"{_EMOJI_BY_EVENT_TYPE['SIGNAL_ONLY']} <b>{title}</b>",
        "",
        "<b>Acci\u00F3n manual:</b>",
        "Revisar oportunidad. No fue ejecutada en paper.",
    ]
    reason_text = str(raw_reason or "").strip()
    if reason_text:
        lines.append("")
        lines.append("<b>Motivo:</b>")
        lines.append(html.escape(reason_text))
    lines.append("")
    lines.append(f"<b>Precio ref:</b> {_fmt_price(reference_price)}")
    if requested_notional is not None:
        lines.append(
            f"<b>Monto sugerido:</b> {_fmt_amount(requested_notional)} {quote}"
        )
    if sl is not None:
        lines.append(f"<b>Stop loss:</b> {_fmt_price(sl)}")
    if tp is not None:
        lines.append(f"<b>Take profit:</b> {_fmt_price(tp)}")
    if time_lines:
        lines.append("")
        lines.extend(time_lines)
    lines.append("")
    lines.append("<b>Estado:</b>")
    lines.append(_SPANISH_DISCLAIMER_SIGNAL_ONLY)
    return "\n".join(lines)


def _format_exit_card(
    *,
    symbol: str,
    metadata: dict[str, Any],
    quote: str,
    emoji: str,
    title: str,
    manual_action_es: str,
    time_lines: list[str] | None = None,
) -> str:
    head = f"{title} \u2014 {html.escape(symbol)}"
    entry = metadata.get("entry_average_price")
    exit_price = metadata.get("fill_price")
    realized = metadata.get("realized_pnl")
    return_pct = metadata.get("return_pct")
    lines = [
        f"{emoji} <b>{head}</b>",
        "",
        "<b>Acci\u00F3n manual:</b>",
        manual_action_es,
        "",
        f"<b>Entry promedio:</b> {_fmt_price(entry)}",
        f"<b>Exit paper:</b> {_fmt_price(exit_price)}",
        f"<b>P&amp;L realizado:</b> {_fmt_signed_amount(realized)} {quote}",
    ]
    if return_pct is not None:
        lines.append(f"<b>Return:</b> {_fmt_signed_pct(return_pct)}")
    if time_lines:
        lines.append("")
        lines.extend(time_lines)
    lines.append("")
    lines.append("<b>Estado:</b>")
    lines.append(_SPANISH_DISCLAIMER_PAPER_NO_REAL)
    return "\n".join(lines)


def _format_order_rejected_card(
    *, symbol: str, metadata: dict[str, Any], time_lines: list[str] | None = None
) -> str:
    head = f"ORDEN RECHAZADA \u2014 {html.escape(symbol)}"
    reason = str(metadata.get("reason") or "unspecified")
    lines = [
        f"{_EMOJI_BY_EVENT_TYPE['ORDER_REJECTED']} <b>{head}</b>",
        "",
        "<b>Motivo:</b>",
        html.escape(reason),
        "",
        "<b>Acci\u00F3n manual:</b>",
        "No copiar autom\u00E1ticamente. Revisar s\u00F3lo si se repite demasiado.",
    ]
    if time_lines:
        lines.append("")
        lines.extend(time_lines)
    lines.append("")
    lines.append("<b>Estado:</b>")
    lines.append("Paper-only")
    return "\n".join(lines)


def _format_error_card(
    *, event: dict[str, Any], time_lines: list[str] | None = None
) -> str:
    title = str(event.get("human_title") or "ERROR")
    manual = str(event.get("manual_action") or "Investigar logs.")
    short_message = str(event.get("human_message") or "")[:240]
    lines = [
        f"{_EMOJI_BY_EVENT_TYPE['ERROR']} <b>{html.escape(title)}</b>",
        "",
        "<b>Acci\u00F3n manual:</b>",
        html.escape(manual),
    ]
    if short_message:
        lines.extend(["", html.escape(short_message)])
    if time_lines:
        lines.append("")
        lines.extend(time_lines)
    lines.append("")
    lines.append("<b>Estado:</b>")
    lines.append(_SPANISH_DISCLAIMER_PAPER_MANUAL)
    return "\n".join(lines)


def _format_warning_card(
    *, event: dict[str, Any], time_lines: list[str] | None = None
) -> str:
    title = str(event.get("human_title") or "Warning")
    metadata = event.get("metadata") or {}
    raw = str(metadata.get("raw_warning") or event.get("human_message") or "")[:240]
    lines = [
        f"{_EMOJI_BY_EVENT_TYPE['WARNING']} <b>{html.escape(title)}</b>",
        "",
        html.escape(raw),
    ]
    if time_lines:
        lines.append("")
        lines.extend(time_lines)
    lines.append("")
    lines.append("<b>Estado:</b>")
    lines.append(_SPANISH_DISCLAIMER_PAPER_MANUAL)
    return "\n".join(lines)


def _format_generic_card(
    *, event: dict[str, Any], time_lines: list[str] | None = None
) -> str:
    title = str(event.get("human_title") or event.get("event_type") or "Event")
    manual = str(event.get("manual_action") or "").strip()
    lines = [f"<b>{html.escape(title)}</b>"]
    if manual:
        lines.append("")
        lines.append("<b>Acci\u00F3n manual:</b>")
        lines.append(html.escape(manual))
    if time_lines:
        lines.append("")
        lines.extend(time_lines)
    lines.append("")
    lines.append("<b>Estado:</b>")
    lines.append(_SPANISH_DISCLAIMER_PAPER_MANUAL)
    return "\n".join(lines)


def _build_time_lines(
    *, event: dict[str, Any], tz_name: str
) -> list[str]:
    """Return ``['<b>Hora local:</b> HH:MM ART', '<b>UTC:</b> HH:MM']``.

    Source preference: per-event ``metadata.occurred_at`` (the actual time the
    paper event happened) over ``created_at`` (the time the semantic layer
    rendered the event). Returns an empty list when no parseable timestamp is
    available so the renderers can skip the section cleanly.
    """

    metadata = event.get("metadata") or {}
    occurred = metadata.get("occurred_at") if isinstance(metadata, dict) else None
    candidate = str(occurred or event.get("created_at") or "").strip()
    if not candidate:
        return []
    local = local_display_for_iso(candidate, tz_name=tz_name)
    if local is None:
        return []
    return [
        f"<b>Hora local:</b> {local['time_local']} {local['tz_label']}",
        f"<b>UTC:</b> {local['time_utc']}",
    ]


# --- Formatting helpers -----------------------------------------------------


def _quote_label(value: Any) -> str:
    text = str(value or "").strip().upper()
    return text or "USDT"


def _small_sample_warning(summary: dict[str, Any]) -> bool:
    warnings = summary.get("warnings") or []
    for warning in warnings:
        text = str(warning or "")
        if text.startswith("small_sample_size:"):
            return True
    return False


def _fmt_price(value: Any) -> str:
    parsed = _safe_float(value)
    if parsed is None:
        return "n/a"
    return f"{parsed:,.2f}"


def _fmt_amount(value: Any) -> str:
    parsed = _safe_float(value)
    if parsed is None:
        return "n/a"
    return f"{parsed:,.2f}"


def _fmt_signed_amount(value: Any) -> str:
    parsed = _safe_float(value)
    if parsed is None:
        return "n/a"
    sign = "+" if parsed >= 0 else "\u2212"  # minus sign for negatives
    return f"{sign}{abs(parsed):,.2f}"


def _fmt_signed_pct(value: Any) -> str:
    parsed = _safe_float(value)
    if parsed is None:
        return "n/a"
    sign = "+" if parsed >= 0 else "\u2212"
    return f"{sign}{abs(parsed) * 100.0:.2f}%"


def _fmt_pct_int(value: Any) -> str:
    parsed = _safe_float(value)
    if parsed is None:
        return "n/a"
    return f"{round(parsed * 100.0)}%"


def _fmt_int(value: Any) -> str:
    if value is None:
        return "n/a"
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return str(value)


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _default_sender(*, bot_token: str, chat_id: str, text: str) -> dict[str, Any]:
    return send_telegram_message(
        bot_token=bot_token,
        chat_id=chat_id,
        text=text,
        parse_mode=_DEFAULT_PARSE_MODE,
    )


def _load_or_build_semantic_layer(
    *,
    artifacts_root: Path,
    rebuild: bool,
    moment: datetime,
) -> dict[str, Any]:
    semantic_dir = artifacts_root / "semantic"
    summary_path = semantic_dir / "crypto_semantic_summary.json"
    events_path = semantic_dir / "crypto_semantic_events.json"
    if not rebuild and summary_path.exists() and events_path.exists():
        summary = _load_json(summary_path, default={})
        events = _load_json(events_path, default=[])
        if isinstance(summary, dict) and isinstance(events, list):
            return {"summary": summary, "events": events}
    return build_semantic_layer(
        artifacts_dir=artifacts_root,
        output_dir=semantic_dir,
        write=True,
        now=moment,
    )


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"sent_event_ids": [], "paper_only": True}
    payload = _load_json(path, default=None)
    if not isinstance(payload, dict):
        return {"sent_event_ids": [], "paper_only": True}
    if not isinstance(payload.get("sent_event_ids"), list):
        payload["sent_event_ids"] = []
    return payload


def _save_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )


def _load_json(path: Path, *, default: Any) -> Any:
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = notify_crypto_paper_telegram(
        artifacts_dir=args.artifacts_dir,
        state_path=args.state_path,
        dry_run=bool(args.dry_run),
        daily_summary=bool(args.daily_summary),
        daily_summary_only=bool(args.daily_summary_only),
        min_severity=str(args.min_severity),
        force=bool(args.force),
        rebuild_semantic=bool(args.rebuild_semantic),
        bootstrap_dedupe=bool(args.bootstrap_dedupe),
        include_order_rejected=bool(args.include_order_rejected),
        include_signal_only=bool(args.include_signal_only),
        local_tz=args.local_tz,
    )
    sys.stdout.write(
        json.dumps(
            {
                "ok": result.get("ok"),
                "paper_only": result.get("paper_only"),
                "live_trading": result.get("live_trading"),
                "dry_run": result.get("dry_run"),
                "daily_summary_only": result.get("daily_summary_only"),
                "bootstrap_dedupe": result.get("bootstrap_dedupe"),
                "marked_count": result.get("marked_count"),
                "considered_count": result.get("considered_count"),
                "sent_count": len(result.get("sent") or []),
                "skipped_count": len(result.get("skipped") or []),
                "sent_event_ids": result.get("sent_event_ids") or [],
                "skipped_event_ids": result.get("skipped_event_ids") or [],
                "include_signal_only": result.get("include_signal_only"),
                "local_tz": result.get("local_tz"),
                "min_severity": result.get("min_severity"),
                "chat_id_masked": result.get("chat_id_masked"),
                "state_path": result.get("state_path"),
                "reason": result.get("reason"),
            },
            sort_keys=True,
        )
        + "\n"
    )
    if args.bootstrap_dedupe:
        sys.stdout.write(
            f"[CRYPTO-TELEGRAM-BOOTSTRAP] marked {result.get('marked_count') or 0} "
            f"event_ids as already-sent (considered {result.get('considered_count') or 0}, "
            f"min_severity={result.get('min_severity')}). No Telegram contact made.\n"
        )
    if args.dry_run:
        for message in result.get("messages") or []:
            sys.stdout.write("---\n")
            sys.stdout.write(message + "\n")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
