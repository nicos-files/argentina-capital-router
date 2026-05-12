"""CLI to compare a daily capital plan against a manual execution log.

Manual review only. No network. No broker. No live trading. No orders.

Inputs:
- ``--plan``        Path to a ``daily_capital_plan.json`` produced by
                    ``src.tools.run_daily_capital_plan``.
- ``--executions``  Path to a manual execution log JSON.
- ``--usdars-rate`` Optional ARS-per-USD rate for converting ARS notional/fees.
- ``--artifacts-dir`` Where to write the JSON comparison and Markdown report.

Outputs:
- ``<artifacts-dir>/manual_execution/manual_execution_comparison.json``
- ``<artifacts-dir>/manual_execution/manual_execution_report.md``

The tool never writes ``execution.plan`` or ``final_decision.json`` and never
performs any network call.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.manual_execution.execution_tracker import (
    ExecutionComparisonSummary,
    compare_plan_to_manual_executions,
    write_execution_comparison_artifacts,
)
from src.recommendations.writer import dataclass_to_dict


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_ARTIFACTS_DIR = _REPO_ROOT / "artifacts"

_EXIT_OK = 0
_EXIT_INVALID = 1
_EXIT_USAGE = 2


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare a daily capital plan to a manual execution log. Manual "
            "review only - no live trading, no broker automation, no orders, "
            "no network."
        )
    )
    parser.add_argument(
        "--plan",
        required=True,
        help="Path to a daily_capital_plan.json artifact.",
    )
    parser.add_argument(
        "--executions",
        required=True,
        help="Path to a manual execution log JSON.",
    )
    parser.add_argument(
        "--artifacts-dir",
        default=str(_DEFAULT_ARTIFACTS_DIR),
        help="Directory under which to write the comparison artifacts.",
    )
    parser.add_argument(
        "--usdars-rate",
        type=float,
        default=None,
        help="Optional ARS-per-USD rate used to convert ARS notional/fees.",
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Print a machine-readable JSON summary instead of human text.",
    )
    return parser


def _summary_payload(summary: ExecutionComparisonSummary) -> dict:
    payload = dataclass_to_dict(summary)
    # Round to two decimals for printed output without mutating the artifact.
    return payload


def _print_human_summary(
    summary: ExecutionComparisonSummary, artifacts: dict[str, str]
) -> None:
    print("Manual review only. No live trading. No broker automation.")
    print(f"as_of: {summary.as_of}")
    print(f"plan: {summary.plan_path}")
    print(f"executions: {summary.execution_log_path}")
    print(f"  follow_rate_pct: {summary.follow_rate_pct:.1f}")
    print(
        f"  total_recommended_usd: {summary.total_recommended_usd:.2f}"
    )
    print(
        "  total_executed_usd_estimate: "
        f"{summary.total_executed_usd_estimate:.2f}"
    )
    print(f"  total_fees_estimate: {summary.total_fees_estimate:.2f}")
    print(
        f"  matched={summary.matched_symbols} "
        f"partial={summary.partial_symbols} "
        f"missed={summary.missed_symbols} "
        f"extra={summary.extra_symbols}"
    )
    if summary.warnings:
        print(f"  warnings ({len(summary.warnings)}):")
        for w in summary.warnings:
            print(f"    - {w}")
    print("artifacts:")
    for name, path in artifacts.items():
        print(f"  - {name}: {path}")


def run(args: argparse.Namespace) -> int:
    plan_path = Path(args.plan).expanduser()
    log_path = Path(args.executions).expanduser()
    try:
        summary = compare_plan_to_manual_executions(
            plan_path, log_path, default_usdars_rate=args.usdars_rate
        )
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return _EXIT_INVALID

    artifacts = write_execution_comparison_artifacts(
        summary, args.artifacts_dir
    )

    if args.as_json:
        payload = _summary_payload(summary)
        payload["artifacts"] = artifacts
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_human_summary(summary, artifacts)
    return _EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse already printed the error; normalize to usage exit code.
        return _EXIT_USAGE if int(exc.code or 0) != 0 else _EXIT_OK
    return run(args)


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    raise SystemExit(main())
