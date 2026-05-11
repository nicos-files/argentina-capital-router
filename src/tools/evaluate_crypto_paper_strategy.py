from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from src.execution.crypto_paper_evaluation import evaluate_crypto_paper_strategy


def run_evaluate_crypto_paper_strategy(
    *,
    run_id: str,
    base_path: str = "runs",
    artifacts_dir: str | None = None,
    output_dir: str | None = None,
) -> dict[str, Any]:
    if not _flag("ENABLE_CRYPTO_PAPER_EVALUATION"):
        return {"status": "SKIPPED", "reason": "crypto_paper_evaluation_disabled"}

    artifact_root = Path(artifacts_dir) if artifacts_dir else Path(base_path) / run_id / "artifacts" / "crypto_paper"
    target_output = Path(output_dir) if output_dir else artifact_root / "evaluation"
    closed_trades, open_trades, metrics, exit_breakdown, fee_report, written, warnings = evaluate_crypto_paper_strategy(
        artifacts_dir=artifact_root,
        output_dir=target_output,
    )
    return {
        "status": "SUCCESS",
        "closed_trades_count": len(closed_trades),
        "open_trades_count": len(open_trades),
        "net_profit": metrics.net_profit,
        "artifacts": {name: str(path) for name, path in written.items()},
        "warnings": warnings,
        "exit_breakdown": exit_breakdown,
        "fee_report": fee_report,
    }


def _flag(name: str) -> bool:
    value = str(os.getenv(name) or "").strip().lower()
    return value in {"1", "true", "yes", "y", "si", "s"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate crypto paper strategy artifacts.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--base-path", default="runs")
    parser.add_argument("--artifacts-dir")
    parser.add_argument("--output-dir")
    parser.add_argument("--as-of")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = run_evaluate_crypto_paper_strategy(
        run_id=args.run_id,
        base_path=args.base_path,
        artifacts_dir=args.artifacts_dir,
        output_dir=args.output_dir,
    )
    print("[EVALUATE-CRYPTO-PAPER-STRATEGY]")
    print(f"- status: {result['status']}")
    if result["status"] == "SUCCESS":
        print(f"- closed_trades_count: {result['closed_trades_count']}")
        print(f"- open_trades_count: {result['open_trades_count']}")
        print(f"- net_profit: {float(result['net_profit']):.6f}")
        print(f"- artifacts: {result['artifacts']}")
    else:
        print(f"- reason: {result.get('reason')}")


if __name__ == "__main__":
    main()
