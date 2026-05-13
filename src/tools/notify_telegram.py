"""CLI: send a Telegram notification for a daily capital plan.

Manual review only. No live trading. No broker automation. No orders.

Bot tokens and chat IDs are loaded exclusively from CLI arguments or
environment variables (``TELEGRAM_BOT_TOKEN`` / ``TELEGRAM_CHAT_ID``); they
are never read from committed config files.

In dry-run mode this command does not require credentials and does not make
any network call - it simply prints the message that would be sent.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

from src.notifications.telegram_notifier import (
    TelegramConfig,
    load_telegram_config,
    send_telegram_message,
)
from src.reports.telegram_summary import (
    format_daily_plan_telegram_message,
    load_daily_plan_for_telegram,
    load_execution_comparison_for_telegram,
)


_EXIT_OK = 0
_EXIT_FAILURE = 1
_EXIT_USAGE = 2


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Send a Telegram notification summarising a daily capital plan. "
            "Manual review only - no live trading, no broker automation, no "
            "orders. Dry-run mode does not require credentials and makes no "
            "network call."
        )
    )
    parser.add_argument(
        "--plan",
        required=True,
        help="Path to a daily_capital_plan.json artifact.",
    )
    parser.add_argument(
        "--execution-comparison",
        default=None,
        help=(
            "Optional path to a manual_execution_comparison.json artifact. "
            "When provided, follow rate and match counts are included."
        ),
    )
    parser.add_argument(
        "--bot-token",
        default=None,
        help=(
            "Telegram bot token. Prefer the TELEGRAM_BOT_TOKEN environment "
            "variable. Never commit this value."
        ),
    )
    parser.add_argument(
        "--chat-id",
        default=None,
        help=(
            "Telegram chat id. Prefer the TELEGRAM_CHAT_ID environment "
            "variable. Never commit this value."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Print the message preview without sending. Does not require "
            "bot token or chat id and makes no network call."
        ),
    )
    parser.add_argument(
        "--max-allocations",
        type=int,
        default=8,
        help="Maximum number of long-term allocations to include.",
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit a machine-readable JSON result instead of human text.",
    )
    return parser


def _format_message(args: argparse.Namespace) -> str:
    plan = load_daily_plan_for_telegram(args.plan)
    comparison = load_execution_comparison_for_telegram(
        args.execution_comparison
    )
    return format_daily_plan_telegram_message(
        plan,
        execution_comparison=comparison,
        max_allocations=int(args.max_allocations),
    )


def _human_summary(
    result: dict, plan_path: str, comparison_path: Optional[str]
) -> None:
    print("Manual review only. No live trading. No broker automation.")
    print(f"plan: {plan_path}")
    if comparison_path:
        print(f"execution_comparison: {comparison_path}")
    print(f"dry_run: {result.get('dry_run', False)}")
    print(f"sent: {result.get('sent', False)}")
    print(f"message_length: {result.get('message_length', 0)}")
    preview = result.get("message_preview")
    if preview is not None:
        print("--- message preview ---")
        print(preview, end="" if preview.endswith("\n") else "\n")
        print("--- end preview ---")


def run(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    try:
        message = _format_message(args)
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return _EXIT_FAILURE, {"ok": False, "error": str(exc)}

    plan_path = str(Path(args.plan))
    comparison_path = (
        str(Path(args.execution_comparison))
        if args.execution_comparison
        else None
    )

    if args.dry_run:
        config: Optional[TelegramConfig] = None
    else:
        try:
            config = load_telegram_config(
                bot_token=args.bot_token, chat_id=args.chat_id
            )
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return _EXIT_FAILURE, {"ok": False, "error": str(exc)}

    try:
        if args.dry_run:
            # Dry-run never requires real credentials; use a placeholder
            # config purely to satisfy the function signature. The notifier's
            # dry-run branch short-circuits before touching token/chat_id.
            placeholder = TelegramConfig(
                bot_token="dry-run", chat_id="dry-run"
            )
            send_result = send_telegram_message(
                placeholder, message, dry_run=True
            )
        else:
            assert config is not None  # narrowed above
            send_result = send_telegram_message(config, message)
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return _EXIT_FAILURE, {"ok": False, "error": str(exc)}

    summary: dict[str, Any] = {
        "ok": True,
        "dry_run": bool(send_result.get("dry_run", False)),
        "sent": bool(send_result.get("sent", False)),
        "message_length": int(send_result.get("message_length", len(message))),
        "plan_path": plan_path,
        "execution_comparison_path": comparison_path,
    }
    if args.dry_run:
        summary["message_preview"] = send_result.get("message_preview", message)
    return _EXIT_OK, summary


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return _EXIT_USAGE if int(exc.code or 0) != 0 else _EXIT_OK

    exit_code, summary = run(args)
    if args.as_json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    elif exit_code == _EXIT_OK:
        _human_summary(
            summary,
            plan_path=summary.get("plan_path", str(args.plan)),
            comparison_path=summary.get("execution_comparison_path"),
        )
    return exit_code


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    raise SystemExit(main())
