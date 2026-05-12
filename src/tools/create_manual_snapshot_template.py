"""CLI to generate a private manual snapshot from a committed template.

Manual review only. No network. No broker. No live trading. No orders.

This tool simply copies a committed template JSON, stamps a chosen ``as_of``
date and snapshot id, and writes the result under ``snapshots/`` (or any
explicit path the user supplies). The user is then expected to open the file
and fill in real placeholder values manually before running the validator and
the daily plan tool.

It never:
- contacts the network
- talks to any broker
- writes ``execution.plan`` or ``final_decision.json``
- imports crypto runtimes
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[2]
_MARKET_TEMPLATE = (
    _REPO_ROOT / "config" / "data_inputs" / "manual_market_snapshot.template.json"
)
_PORTFOLIO_TEMPLATE = (
    _REPO_ROOT / "config" / "portfolio" / "manual_portfolio_snapshot.template.json"
)
_DEFAULT_OUT_DIR = _REPO_ROOT / "snapshots"


_EXIT_OK = 0
_EXIT_USAGE = 2


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a private manual snapshot (market and/or portfolio) from "
            "the committed templates. Manual review only - no live trading, no "
            "broker automation, no orders, no network."
        )
    )
    parser.add_argument(
        "--kind",
        choices=("market", "portfolio", "both"),
        required=True,
        help="Which snapshot template to generate.",
    )
    parser.add_argument(
        "--date",
        required=True,
        help="Target as_of date in YYYY-MM-DD form (also used for snapshot id and default filename).",
    )
    parser.add_argument(
        "--out-dir",
        default=str(_DEFAULT_OUT_DIR),
        help=(
            "Base directory for generated snapshots. Defaults to "
            "the repository's snapshots/ folder (gitignored)."
        ),
    )
    parser.add_argument(
        "--market-out",
        default=None,
        help="Explicit output path for the market snapshot (overrides --out-dir).",
    )
    parser.add_argument(
        "--portfolio-out",
        default=None,
        help="Explicit output path for the portfolio snapshot (overrides --out-dir).",
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


def _load_template(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"template not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON template: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path}: template root must be a JSON object")
    return data


def _stamp_market(data: dict[str, Any], target_date: str) -> dict[str, Any]:
    """Return a copy of the market template with as_of/snapshot_id stamped."""
    stamped = json.loads(json.dumps(data))
    stamped["as_of"] = target_date
    stamped["snapshot_id"] = f"manual-market-{target_date}"
    # Propagate target date into every entry's as_of for consistency. Notes /
    # placeholder values stay untouched so the user still sees the TODO hints.
    for quote in stamped.get("quotes", []) or []:
        if isinstance(quote, dict):
            quote["as_of"] = target_date
    for entry in (stamped.get("fx_rates") or {}).values():
        if isinstance(entry, dict):
            entry["as_of"] = target_date
    for entry in (stamped.get("rates") or {}).values():
        if isinstance(entry, dict):
            entry["as_of"] = target_date
    return stamped


def _stamp_portfolio(data: dict[str, Any], target_date: str) -> dict[str, Any]:
    """Return a copy of the portfolio template with as_of/snapshot_id stamped."""
    stamped = json.loads(json.dumps(data))
    stamped["as_of"] = target_date
    stamped["snapshot_id"] = f"manual-portfolio-{target_date}"
    return stamped


def _default_market_path(out_dir: Path, target_date: str) -> Path:
    return out_dir / "market" / f"{target_date}.json"


def _default_portfolio_path(out_dir: Path, target_date: str) -> Path:
    return out_dir / "portfolio" / f"{target_date}.json"


def _write_json(path: Path, payload: dict[str, Any], *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"refusing to overwrite existing file (pass --overwrite to replace): {path}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    path.write_text(serialized, encoding="utf-8")


def generate(args: argparse.Namespace) -> list[Path]:
    """Generate the requested snapshot file(s) and return their paths."""
    target_date = _validate_date(args.date)
    out_dir = Path(args.out_dir).expanduser().resolve()
    generated: list[Path] = []

    if args.kind in ("market", "both"):
        market_data = _stamp_market(_load_template(_MARKET_TEMPLATE), target_date)
        market_path = (
            Path(args.market_out).expanduser().resolve()
            if args.market_out
            else _default_market_path(out_dir, target_date)
        )
        _write_json(market_path, market_data, overwrite=args.overwrite)
        generated.append(market_path)

    if args.kind in ("portfolio", "both"):
        portfolio_data = _stamp_portfolio(
            _load_template(_PORTFOLIO_TEMPLATE), target_date
        )
        portfolio_path = (
            Path(args.portfolio_out).expanduser().resolve()
            if args.portfolio_out
            else _default_portfolio_path(out_dir, target_date)
        )
        _write_json(portfolio_path, portfolio_data, overwrite=args.overwrite)
        generated.append(portfolio_path)

    return generated


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    try:
        generated = generate(args)
    except (ValueError, FileNotFoundError, FileExistsError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return _EXIT_USAGE

    print("Manual review only. No live trading. No broker automation.")
    print("Generated template snapshot(s):")
    for path in generated:
        print(f"  - {path}")
    print(
        "Next steps: open each file and replace the TODO placeholders, then "
        "run `python -m src.tools.validate_manual_inputs` to verify."
    )
    return _EXIT_OK


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    raise SystemExit(main())
