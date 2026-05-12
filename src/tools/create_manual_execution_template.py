"""CLI to generate a private manual execution log from the committed template.

Manual review only. No network. No broker. No live trading. No orders.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATE_PATH = (
    _REPO_ROOT
    / "config"
    / "manual_execution"
    / "manual_executions.template.json"
)
_DEFAULT_OUT_DIR = _REPO_ROOT / "snapshots" / "manual_execution"


_EXIT_OK = 0
_EXIT_USAGE = 2


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a private manual execution log from the committed "
            "template. Manual review only - no live trading, no broker "
            "automation, no orders, no network."
        )
    )
    parser.add_argument(
        "--date",
        required=True,
        help="Target as_of date in YYYY-MM-DD form (used for filename and execution_log_id).",
    )
    parser.add_argument(
        "--out",
        default=None,
        help=(
            "Explicit output path. Defaults to "
            "snapshots/manual_execution/<date>.json under the repository root."
        ),
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite the destination file if it already exists.",
    )
    return parser


def _validate_date(raw: str) -> str:
    try:
        datetime.strptime(raw, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(
            f"--date must be in YYYY-MM-DD form (got {raw!r}): {exc}"
        ) from exc
    return raw


def _load_template() -> dict[str, Any]:
    if not _TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"template not found: {_TEMPLATE_PATH}")
    try:
        with _TEMPLATE_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{_TEMPLATE_PATH}: invalid JSON template: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise ValueError(
            f"{_TEMPLATE_PATH}: template root must be a JSON object"
        )
    return data


def _stamp(data: dict[str, Any], target_date: str) -> dict[str, Any]:
    stamped = json.loads(json.dumps(data))
    stamped["as_of"] = target_date
    stamped["execution_log_id"] = f"manual-executions-{target_date}"
    for exe in stamped.get("executions", []) or []:
        if isinstance(exe, dict):
            exe["executed_at"] = target_date
            exe["plan_id"] = target_date
    return stamped


def _default_output_path(target_date: str) -> Path:
    return _DEFAULT_OUT_DIR / f"{target_date}.json"


def _write(path: Path, payload: dict[str, Any], *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"refusing to overwrite existing file (pass --overwrite to replace): {path}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    path.write_text(serialized, encoding="utf-8")


def generate(args: argparse.Namespace) -> Path:
    target_date = _validate_date(args.date)
    payload = _stamp(_load_template(), target_date)
    out_path = (
        Path(args.out).expanduser().resolve()
        if args.out
        else _default_output_path(target_date)
    )
    _write(out_path, payload, overwrite=args.overwrite)
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    try:
        path = generate(args)
    except (ValueError, FileNotFoundError, FileExistsError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return _EXIT_USAGE

    print("Manual review only. No live trading. No broker automation.")
    print(f"Generated manual execution log template: {path}")
    print(
        "Next steps: open the file, replace every TODO with the actual trades "
        "you placed in your broker, and run "
        "`python -m src.tools.compare_manual_execution` to compare it against "
        "the daily plan."
    )
    return _EXIT_OK


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    raise SystemExit(main())
