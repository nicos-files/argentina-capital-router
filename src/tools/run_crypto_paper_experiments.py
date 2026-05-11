from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from src.research.crypto_paper_experiments import (
    load_crypto_paper_experiment_candles,
    load_crypto_paper_experiment_config,
    run_crypto_paper_experiments,
)


def run_crypto_paper_experiments_tool(
    *,
    experiment_config: str,
    candles_json: str,
    output_dir: str | None = None,
    max_configs: int | None = None,
) -> dict[str, Any]:
    if not _flag("ENABLE_CRYPTO_PAPER_EXPERIMENTS"):
        return {"status": "SKIPPED", "reason": "crypto_paper_experiments_disabled"}

    config_path = Path(experiment_config)
    candles_path = Path(candles_json)
    if not config_path.exists():
        return {"status": "FAILED", "reason": f"missing_experiment_config:{config_path}"}
    if not candles_path.exists():
        return {"status": "FAILED", "reason": f"missing_candles_file:{candles_path}"}

    payload = load_crypto_paper_experiment_config(config_path)
    candles = load_crypto_paper_experiment_candles(candles_path)
    target_dir = Path(output_dir) if output_dir else Path("artifacts") / "crypto_paper" / "experiments" / str(payload.get("experiment_name") or "crypto_paper_experiment")
    try:
        summary, rankings, written = run_crypto_paper_experiments(
            experiment_config=payload,
            candles_by_symbol=candles,
            output_dir=target_dir,
            max_configs=max_configs,
        )
    except Exception as exc:
        return {"status": "FAILED", "reason": str(exc)}
    return {
        "status": "SUCCESS",
        "experiment_name": summary["experiment_name"],
        "configs_tested": summary["configs_tested"],
        "eligible_configs": summary["eligible_configs"],
        "best_config_id": summary["best_config_id"],
        "artifacts": {name: str(path) for name, path in written.items()},
        "warnings": summary["warnings"],
        "output_dir": str(target_dir),
        "rankings_count": len(rankings),
    }


def _flag(name: str) -> bool:
    value = str(os.getenv(name) or "").strip().lower()
    return value in {"1", "true", "yes", "y", "si", "s"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run crypto paper parameter experiments.")
    parser.add_argument("--experiment-config", required=True)
    parser.add_argument("--candles-json", required=True)
    parser.add_argument("--output-dir")
    parser.add_argument("--max-configs", type=int)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = run_crypto_paper_experiments_tool(
        experiment_config=args.experiment_config,
        candles_json=args.candles_json,
        output_dir=args.output_dir,
        max_configs=args.max_configs,
    )
    print("[CRYPTO-PAPER-EXPERIMENTS]")
    print(f"- status: {result['status']}")
    if result["status"] == "SUCCESS":
        print(f"- experiment_name: {result['experiment_name']}")
        print(f"- configs_tested: {result['configs_tested']}")
        print(f"- eligible_configs: {result['eligible_configs']}")
        print(f"- best_config_id: {result['best_config_id']}")
        print(f"- output_dir: {result['output_dir']}")
    else:
        print(f"- reason: {result.get('reason')}")


if __name__ == "__main__":
    main()
