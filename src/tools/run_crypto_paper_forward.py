from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from src.execution.crypto_paper_forward import run_crypto_paper_forward


def run_crypto_paper_forward_tool(
    *,
    candidate_config: str,
    artifacts_dir: str = "artifacts/crypto_paper",
    as_of: str | None = None,
    prices_json: str | None = None,
    dry_run: bool = True,
    provider: Any | None = None,
) -> dict[str, Any]:
    if not _flag("ENABLE_CRYPTO_PAPER_FORWARD"):
        return {"status": "SKIPPED", "reason": "crypto_paper_forward_disabled"}
    try:
        return run_crypto_paper_forward(
            candidate_config=candidate_config,
            artifacts_dir=artifacts_dir,
            as_of=as_of,
            prices_json=prices_json,
            dry_run=dry_run,
            provider=provider,
        )
    except Exception as exc:
        return {"status": "FAILED", "reason": str(exc)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run crypto paper-forward operational loop from a candidate config.")
    parser.add_argument("--candidate-config", required=True)
    parser.add_argument("--artifacts-dir", default="artifacts/crypto_paper")
    parser.add_argument("--as-of")
    parser.add_argument("--prices-json")
    parser.add_argument("--dry-run", default="true")
    return parser


def _flag(name: str) -> bool:
    value = str(os.getenv(name) or "").strip().lower()
    return value in {"1", "true", "yes", "y", "si", "s"}


def _parse_bool(value: str | None) -> bool:
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "si", "s", ""}


def main() -> None:
    args = build_parser().parse_args()
    result = run_crypto_paper_forward_tool(
        candidate_config=args.candidate_config,
        artifacts_dir=args.artifacts_dir,
        as_of=args.as_of,
        prices_json=args.prices_json,
        dry_run=_parse_bool(args.dry_run),
    )
    print("[CRYPTO-PAPER-FORWARD]")
    print(f"- status: {result['status']}")
    if result["status"] in {"SUCCESS", "PARTIAL"}:
        print(f"- recommendations_count: {result.get('recommendations_count', 0)}")
        print(f"- fills_count: {result.get('fills_count', 0)}")
        print(f"- exits_count: {result.get('exits_count', 0)}")
        print(f"- total_equity: {float(result.get('total_equity', 0.0)):.6f}")
    else:
        print(f"- reason: {result.get('reason')}")


if __name__ == "__main__":
    main()
