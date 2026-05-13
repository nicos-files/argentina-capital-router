"""One-command manual daily workflow orchestrator.

Manual review only. No network. No broker. No live trading. No orders.

This tool composes the existing manual-input CLIs into a single, repeatable
end-of-day workflow:

1. Validate manual market + portfolio snapshots (read-only).
2. Build the daily capital plan and report.
3. Optionally compare a manual execution log against the freshly generated
   plan.
4. Print a concise human-readable summary or a machine-readable JSON blob.

No subprocesses are spawned: all underlying tools are imported and invoked as
Python functions so that the orchestrator inherits every guarantee they
provide (loaders that reject ``live_trading_enabled: true``, writers that
never emit ``execution.plan`` or ``final_decision.json``, and so on).
"""
from __future__ import annotations

import argparse
import json
import sys
from argparse import Namespace
from datetime import date
from pathlib import Path
from typing import Any, Optional

from src.manual_execution.execution_tracker import (
    ExecutionComparisonSummary,
    compare_plan_to_manual_executions,
    write_execution_comparison_artifacts,
)
from src.notifications.telegram_notifier import (
    TelegramConfig,
    load_telegram_config,
    send_telegram_message,
)
from src.recommendations.models import CapitalPlanRecommendation
from src.recommendations.writer import dataclass_to_dict
from src.reports.telegram_summary import (
    format_daily_plan_telegram_message,
    load_daily_plan_for_telegram,
    load_execution_comparison_for_telegram,
)
from src.tools import run_daily_capital_plan as plan_cli
from src.tools import validate_manual_inputs as validate_cli


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_OUTPUTS_DIR = _REPO_ROOT / "snapshots" / "outputs"


_EXIT_OK = 0
_EXIT_FAILURE = 1
_EXIT_USAGE = 2


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the manual daily workflow end-to-end: validate inputs, build "
            "the daily capital plan, and optionally compare a manual "
            "execution log. Manual review only - no live trading, no broker "
            "automation, no orders, no network."
        )
    )
    parser.add_argument(
        "--date",
        default=None,
        help="As-of date in YYYY-MM-DD form. Defaults to today.",
    )
    parser.add_argument(
        "--market-snapshot",
        required=True,
        help="Path to a manual market snapshot JSON file.",
    )
    parser.add_argument(
        "--portfolio-snapshot",
        required=True,
        help="Path to a manual portfolio snapshot JSON file.",
    )
    parser.add_argument(
        "--executions",
        default=None,
        help=(
            "Optional path to a manual execution log JSON. When provided, "
            "the workflow runs the comparison step."
        ),
    )
    parser.add_argument(
        "--artifacts-dir",
        default=None,
        help=(
            "Where to write the daily plan, report, and comparison "
            "artifacts. Defaults to snapshots/outputs/<date>/ under the "
            "repository root."
        ),
    )
    parser.add_argument(
        "--usdars-rate",
        type=float,
        default=None,
        help=(
            "Optional ARS-per-USD rate used by the manual execution "
            "comparison step."
        ),
    )
    parser.add_argument(
        "--carry-from-snapshot",
        action="store_true",
        help=(
            "Forwarded to the daily capital plan builder: derive carry-trade "
            "inputs from the market snapshot."
        ),
    )
    parser.add_argument(
        "--strict-inputs",
        action="store_true",
        help=(
            "Fail when input snapshots are incomplete or carry quality "
            "warnings (delegated to validate_manual_inputs --strict)."
        ),
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit a machine-readable JSON summary to stdout.",
    )

    # Telegram notification flags (all optional; default behavior unchanged).
    parser.add_argument(
        "--notify-telegram",
        action="store_true",
        help=(
            "After a successful workflow run, send a Telegram notification "
            "summarising the plan. Requires TELEGRAM_BOT_TOKEN and "
            "TELEGRAM_CHAT_ID (or --telegram-bot-token / --telegram-chat-id)."
        ),
    )
    parser.add_argument(
        "--telegram-dry-run",
        action="store_true",
        help=(
            "Format the Telegram message and include the preview in the "
            "workflow summary, but do not send. No credentials required."
        ),
    )
    parser.add_argument(
        "--telegram-bot-token",
        default=None,
        help=(
            "Telegram bot token. Prefer the TELEGRAM_BOT_TOKEN environment "
            "variable. Never commit this value."
        ),
    )
    parser.add_argument(
        "--telegram-chat-id",
        default=None,
        help=(
            "Telegram chat id. Prefer the TELEGRAM_CHAT_ID environment "
            "variable. Never commit this value."
        ),
    )
    parser.add_argument(
        "--telegram-max-allocations",
        type=int,
        default=8,
        help="Maximum number of long-term allocations to include in the message.",
    )
    return parser


# ---------------------------------------------------------------------------
# Step helpers
# ---------------------------------------------------------------------------


def _resolve_date(raw: Optional[str]) -> str:
    if raw is None:
        return date.today().isoformat()
    return raw


def _resolve_artifacts_dir(raw: Optional[str], target_date: str) -> Path:
    if raw is not None:
        return Path(raw).expanduser()
    return _DEFAULT_OUTPUTS_DIR / target_date


def _validation_args(
    market_snapshot: str,
    portfolio_snapshot: str,
    *,
    strict: bool,
) -> Namespace:
    return Namespace(
        market_snapshot=market_snapshot,
        portfolio_snapshot=portfolio_snapshot,
        strict=strict,
        as_json=False,
    )


def _plan_args(
    *,
    as_of: str,
    market_snapshot: str,
    portfolio_snapshot: str,
    artifacts_dir: Path,
    carry_from_snapshot: bool,
) -> Namespace:
    """Build a Namespace compatible with run_daily_capital_plan.build_plan.

    Mirrors the defaults from ``run_daily_capital_plan._build_arg_parser`` so
    the helper sees exactly what the underlying CLI would produce. Tactical
    fields are kept at their conservative defaults; the orchestrator only
    exposes ``--carry-from-snapshot`` to the user.
    """
    return Namespace(
        as_of=as_of,
        monthly_contribution_usd=None,
        tactical_capital_usd=0.0,
        simulate_carry=False,
        carry_rate_pct=0.0,
        carry_fx_devaluation_pct=0.0,
        carry_cost_pct=0.0,
        carry_duration_days=7,
        carry_fx_risk_score=50.0,
        carry_liquidity_risk_score=50.0,
        market_snapshot=Path(market_snapshot),
        carry_from_snapshot=bool(carry_from_snapshot),
        carry_rate_key="money_market_monthly_pct",
        carry_expected_fx_key="expected_fx_devaluation_monthly_pct",
        portfolio_snapshot=Path(portfolio_snapshot),
        artifacts_dir=Path(artifacts_dir),
    )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _run_validation(
    args: argparse.Namespace,
) -> tuple[int, dict[str, Any]]:
    val_args = _validation_args(
        args.market_snapshot,
        args.portfolio_snapshot,
        strict=bool(args.strict_inputs),
    )
    return validate_cli.run(val_args)


def _run_plan(
    args: argparse.Namespace,
    target_date: str,
    artifacts_dir: Path,
) -> tuple[CapitalPlanRecommendation, dict[str, Path]]:
    plan_args = _plan_args(
        as_of=target_date,
        market_snapshot=args.market_snapshot,
        portfolio_snapshot=args.portfolio_snapshot,
        artifacts_dir=artifacts_dir,
        carry_from_snapshot=bool(args.carry_from_snapshot),
    )
    return plan_cli.run_daily_capital_plan(plan_args)


def _run_execution_comparison(
    plan_path: Path,
    executions_path: Path,
    artifacts_dir: Path,
    usdars_rate: Optional[float],
) -> tuple[ExecutionComparisonSummary, dict[str, str]]:
    summary = compare_plan_to_manual_executions(
        plan_path, executions_path, default_usdars_rate=usdars_rate
    )
    artifacts = write_execution_comparison_artifacts(summary, artifacts_dir)
    return summary, artifacts


def _run_telegram_notification(
    args: argparse.Namespace,
    plan_path: Path,
    execution_comparison_path: Optional[Path],
) -> dict[str, Any]:
    """Build (and optionally send) the Telegram daily summary.

    Returns a dict with at minimum ``ok``, ``dry_run``, ``sent``,
    ``message_length`` and (in dry-run mode) ``message_preview``. Never
    surfaces the bot token. Raises ``RuntimeError`` on send failure, which
    the caller maps to a non-zero exit code.
    """
    plan_payload = load_daily_plan_for_telegram(plan_path)
    comparison_payload = load_execution_comparison_for_telegram(
        execution_comparison_path
    )
    message = format_daily_plan_telegram_message(
        plan_payload,
        execution_comparison=comparison_payload,
        max_allocations=int(args.telegram_max_allocations),
    )

    dry_run = bool(args.telegram_dry_run) or not bool(args.notify_telegram)
    if dry_run:
        result = send_telegram_message(
            TelegramConfig(bot_token="dry-run", chat_id="dry-run"),
            message,
            dry_run=True,
        )
        return {
            "ok": True,
            "dry_run": True,
            "sent": False,
            "message_length": int(result.get("message_length", len(message))),
            "message_preview": result.get("message_preview", message),
        }

    config = load_telegram_config(
        bot_token=args.telegram_bot_token, chat_id=args.telegram_chat_id
    )
    result = send_telegram_message(config, message)
    return {
        "ok": True,
        "dry_run": False,
        "sent": bool(result.get("sent", True)),
        "message_length": int(result.get("message_length", len(message))),
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _print_human_summary(report: dict[str, Any]) -> None:
    print("Manual review only. No live trading. No broker automation.")
    print(f"argentina-capital-router manual daily workflow")
    print(f"  date: {report['date']}")
    print(f"  artifacts_dir: {report['artifacts_dir']}")
    print(f"  market_snapshot: {report['market_snapshot']}")
    print(f"  portfolio_snapshot: {report['portfolio_snapshot']}")
    print(f"  input_validation_status: {report['input_validation_status']}")
    if report.get("strict_failures"):
        print(f"  strict_failures ({len(report['strict_failures'])}):")
        for f in report["strict_failures"]:
            print(f"    - {f}")
    plan = report.get("plan") or {}
    print("  daily_plan:")
    print(f"    decision: {plan.get('decision')}")
    print(f"    rationale: {plan.get('rationale')}")
    print(
        "    long_term_allocations: "
        f"{plan.get('long_term_allocations_count', 0)}"
    )
    if plan.get("skipped_allocations_count", 0):
        print(
            "    skipped_allocations: "
            f"{plan['skipped_allocations_count']}"
        )
    if plan.get("portfolio_total_value_usd") is not None:
        print(
            "    portfolio_total_value_usd: "
            f"{plan['portfolio_total_value_usd']:.2f}"
        )
    if plan.get("warnings"):
        print(f"    warnings ({len(plan['warnings'])}):")
        for w in plan["warnings"]:
            print(f"      - {w}")
    if report.get("execution_comparison") is not None:
        comp = report["execution_comparison"]
        print("  execution_comparison:")
        print(f"    follow_rate_pct: {comp['follow_rate_pct']:.1f}")
        print(
            f"    matched={comp['matched_symbols']} "
            f"partial={comp['partial_symbols']} "
            f"missed={comp['missed_symbols']} "
            f"extra={comp['extra_symbols']}"
        )
        print(
            "    total_recommended_usd: "
            f"{comp['total_recommended_usd']:.2f}"
        )
        print(
            "    total_executed_usd_estimate: "
            f"{comp['total_executed_usd_estimate']:.2f}"
        )
        print(
            "    total_fees_estimate: "
            f"{comp['total_fees_estimate']:.2f}"
        )
    else:
        print("  execution_comparison: skipped (no --executions provided)")
    telegram = report.get("telegram")
    if telegram is not None:
        print("  telegram:")
        print(f"    ok: {telegram.get('ok')}")
        print(f"    dry_run: {telegram.get('dry_run')}")
        print(f"    sent: {telegram.get('sent')}")
        print(f"    message_length: {telegram.get('message_length')}")
        if telegram.get("error"):
            print(f"    error: {telegram['error']}")
        elif telegram.get("dry_run") and telegram.get("message_preview"):
            print("    --- message preview ---")
            preview = telegram["message_preview"]
            print(preview, end="" if preview.endswith("\n") else "\n")
            print("    --- end preview ---")
    print("  artifacts:")
    for name, path in report["artifacts"].items():
        print(f"    - {name}: {path}")
    print(f"  status: {report['status']}")


def _build_report(
    *,
    target_date: str,
    artifacts_dir: Path,
    args: argparse.Namespace,
    validation_summary: dict[str, Any],
    validation_rc: int,
    recommendation: Optional[CapitalPlanRecommendation],
    plan_paths: dict[str, Path],
    comparison: Optional[ExecutionComparisonSummary],
    comparison_paths: dict[str, str],
    status: str,
    telegram: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "manual_review_only": True,
        "live_trading_enabled": False,
        "date": target_date,
        "market_snapshot": str(args.market_snapshot),
        "portfolio_snapshot": str(args.portfolio_snapshot),
        "artifacts_dir": str(artifacts_dir),
        "input_validation_status": validation_summary.get("status", "unknown"),
        "input_validation_rc": validation_rc,
        "status": status,
        "artifacts": {},
    }
    if validation_summary.get("strict_failures"):
        report["strict_failures"] = list(
            validation_summary["strict_failures"]
        )
    if validation_summary.get("errors"):
        report["input_validation_errors"] = list(
            validation_summary["errors"]
        )

    if recommendation is not None:
        plan = recommendation.plan
        decision = dict(plan.routing_decision)
        report["plan"] = {
            "as_of": plan.as_of,
            "decision": decision.get("decision"),
            "rationale": decision.get("rationale"),
            "monthly_long_term_contribution_usd": float(
                plan.monthly_long_term_contribution_usd
            ),
            "long_term_allocations_count": len(plan.long_term_allocations),
            "skipped_allocations_count": len(plan.skipped_allocations),
            "unallocated_usd": float(plan.unallocated_usd),
            "portfolio_total_value_usd": (
                float(plan.portfolio_total_value_usd)
                if plan.portfolio_total_value_usd is not None
                else None
            ),
            "warnings": list(plan.warnings),
        }
        for name, path in plan_paths.items():
            report["artifacts"][name] = str(path)
        report["daily_plan_path"] = str(plan_paths["daily_capital_plan"])
        report["daily_report_path"] = str(plan_paths["daily_report"])

    if comparison is not None:
        report["execution_comparison"] = {
            "follow_rate_pct": float(comparison.follow_rate_pct),
            "matched_symbols": int(comparison.matched_symbols),
            "partial_symbols": int(comparison.partial_symbols),
            "missed_symbols": int(comparison.missed_symbols),
            "extra_symbols": int(comparison.extra_symbols),
            "total_recommended_usd": float(comparison.total_recommended_usd),
            "total_executed_usd_estimate": float(
                comparison.total_executed_usd_estimate
            ),
            "total_fees_estimate": float(comparison.total_fees_estimate),
            "warnings": list(comparison.warnings),
        }
        for name, path in comparison_paths.items():
            report["artifacts"][name] = str(path)
        report["execution_comparison_path"] = comparison_paths.get(
            "manual_execution_comparison"
        )
        report["follow_rate_pct"] = float(comparison.follow_rate_pct)
    else:
        report["execution_comparison"] = None

    if telegram is not None:
        report["telegram"] = telegram

    return report


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def run(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    target_date = _resolve_date(args.date)
    artifacts_dir = _resolve_artifacts_dir(args.artifacts_dir, target_date)

    validation_rc, validation_summary = _run_validation(args)
    if validation_rc != _EXIT_OK:
        # When validation fails, do not advance to plan/comparison; that
        # matches the underlying CLIs' guarantees and keeps the workflow
        # idempotent (no half-written artifacts).
        report = _build_report(
            target_date=target_date,
            artifacts_dir=artifacts_dir,
            args=args,
            validation_summary=validation_summary,
            validation_rc=validation_rc,
            recommendation=None,
            plan_paths={},
            comparison=None,
            comparison_paths={},
            status="validation_failed",
        )
        return _EXIT_FAILURE, report

    try:
        recommendation, plan_paths = _run_plan(
            args, target_date, artifacts_dir
        )
    except (ValueError, FileNotFoundError) as exc:
        report = _build_report(
            target_date=target_date,
            artifacts_dir=artifacts_dir,
            args=args,
            validation_summary=validation_summary,
            validation_rc=validation_rc,
            recommendation=None,
            plan_paths={},
            comparison=None,
            comparison_paths={},
            status="plan_failed",
        )
        report["plan_error"] = str(exc)
        return _EXIT_FAILURE, report

    comparison: Optional[ExecutionComparisonSummary] = None
    comparison_paths: dict[str, str] = {}
    if args.executions:
        try:
            comparison, comparison_paths = _run_execution_comparison(
                plan_paths["daily_capital_plan"],
                Path(args.executions).expanduser(),
                artifacts_dir,
                args.usdars_rate,
            )
        except (ValueError, FileNotFoundError) as exc:
            report = _build_report(
                target_date=target_date,
                artifacts_dir=artifacts_dir,
                args=args,
                validation_summary=validation_summary,
                validation_rc=validation_rc,
                recommendation=recommendation,
                plan_paths=plan_paths,
                comparison=None,
                comparison_paths={},
                status="comparison_failed",
            )
            report["comparison_error"] = str(exc)
            return _EXIT_FAILURE, report

    telegram_result: Optional[dict[str, Any]] = None
    telegram_failed = False
    if args.notify_telegram or args.telegram_dry_run:
        comparison_path: Optional[Path] = None
        if comparison_paths:
            raw = comparison_paths.get("manual_execution_comparison")
            comparison_path = Path(raw) if raw else None
        try:
            telegram_result = _run_telegram_notification(
                args,
                plan_path=plan_paths["daily_capital_plan"],
                execution_comparison_path=comparison_path,
            )
        except (RuntimeError, ValueError) as exc:
            # Daily artifacts have already been written; surface the failure
            # but keep them. The bot token is never echoed by the notifier so
            # str(exc) is safe to include here.
            telegram_result = {
                "ok": False,
                "dry_run": bool(args.telegram_dry_run),
                "sent": False,
                "error": str(exc),
            }
            telegram_failed = True

    report = _build_report(
        target_date=target_date,
        artifacts_dir=artifacts_dir,
        args=args,
        validation_summary=validation_summary,
        validation_rc=validation_rc,
        recommendation=recommendation,
        plan_paths=plan_paths,
        comparison=comparison,
        comparison_paths=comparison_paths,
        status="telegram_failed" if telegram_failed else "ok",
        telegram=telegram_result,
    )
    exit_code = _EXIT_FAILURE if telegram_failed else _EXIT_OK
    return exit_code, report


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return _EXIT_USAGE if int(exc.code or 0) != 0 else _EXIT_OK

    exit_code, report = run(args)
    if args.as_json:
        # Reuse dataclass_to_dict so any dataclass that slips in is normalized;
        # the report we build already contains primitives only.
        print(json.dumps(dataclass_to_dict(report), indent=2, sort_keys=True))
    else:
        _print_human_summary(report)
    return exit_code


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    raise SystemExit(main())
