from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from src.execution.crypto_paper_history import update_crypto_paper_history


def run_update_crypto_paper_history(
    *,
    run_id: str,
    base_path: str = "runs",
    daily_close_dir: str | None = None,
    history_dir: str | None = None,
    allow_missing: bool = False,
) -> dict[str, Any]:
    if not _flag("ENABLE_CRYPTO_PAPER_HISTORY"):
        return {"status": "SKIPPED", "reason": "crypto_paper_history_disabled"}

    run_root = Path(base_path) / run_id / "artifacts" / "crypto_paper"
    resolved_daily_close = Path(daily_close_dir) if daily_close_dir else run_root / "daily_close"
    resolved_history = Path(history_dir) if history_dir else run_root / "history"

    if not resolved_daily_close.exists() and not allow_missing:
        return {"status": "SUCCESS", "warnings": ["Missing daily close directory."], "artifacts": {}}

    entries, points, summary, symbol_attribution, artifacts, warnings = update_crypto_paper_history(
        daily_close_dir=resolved_daily_close,
        history_dir=resolved_history,
    )
    return {
        "status": "SUCCESS",
        "entries_count": len(entries),
        "equity_points_count": len(points),
        "symbol_attribution_count": len(symbol_attribution),
        "ending_equity": summary.ending_equity,
        "artifacts": {name: str(path) for name, path in artifacts.items()},
        "warnings": warnings,
    }


def _flag(name: str) -> bool:
    value = str(os.getenv(name) or "").strip().lower()
    return value in {"1", "true", "yes", "y", "si", "s"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Update isolated crypto paper performance history.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--base-path", default="runs")
    parser.add_argument("--daily-close-dir")
    parser.add_argument("--history-dir")
    parser.add_argument("--allow-missing", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = run_update_crypto_paper_history(
        run_id=args.run_id,
        base_path=args.base_path,
        daily_close_dir=args.daily_close_dir,
        history_dir=args.history_dir,
        allow_missing=args.allow_missing,
    )
    print("[UPDATE-CRYPTO-PAPER-HISTORY]")
    print(f"- status: {result['status']}")
    if result["status"] == "SUCCESS":
        print(f"- entries_count: {result.get('entries_count', 0)}")
        print(f"- ending_equity: {float(result.get('ending_equity', 0.0)):.6f}")
        print(f"- artifacts: {result.get('artifacts', {})}")
    else:
        print(f"- reason: {result.get('reason')}")


if __name__ == "__main__":
    main()
