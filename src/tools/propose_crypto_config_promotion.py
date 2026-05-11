from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from src.research.crypto_config_promotion import create_crypto_config_promotion_proposal


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CURRENT_CONFIG = ROOT / "config" / "market_universe" / "crypto.json"


def run_propose_crypto_config_promotion(
    *,
    experiment_dir: str,
    current_config: str | None = None,
    output_dir: str | None = None,
    config_id: str | None = None,
    use_best_eligible: bool = False,
    paper_forward_enable: bool = False,
) -> dict[str, Any]:
    if not _flag("ENABLE_CRYPTO_CONFIG_PROMOTION_PROPOSAL"):
        return {"status": "SKIPPED", "reason": "crypto_config_promotion_proposal_disabled"}
    if not config_id and not use_best_eligible:
        return {"status": "FAILED", "reason": "missing_selector"}

    experiment_path = Path(experiment_dir)
    current_config_path = Path(current_config) if current_config else DEFAULT_CURRENT_CONFIG
    target_output = Path(output_dir) if output_dir else _default_output_dir(experiment_path)
    try:
        candidate_config, diff_payload, validation_payload, _, written = create_crypto_config_promotion_proposal(
            experiment_dir=experiment_path,
            current_config_path=current_config_path,
            output_dir=target_output,
            config_id=config_id,
            use_best_eligible=use_best_eligible,
            paper_forward_enable=paper_forward_enable,
        )
    except Exception as exc:
        return {"status": "FAILED", "reason": str(exc)}
    return {
        "status": "SUCCESS",
        "selected_config_id": config_id or "best_eligible",
        "eligible_for_candidate": validation_payload["eligible_for_candidate"],
        "paper_forward_enable": paper_forward_enable,
        "output_dir": str(target_output),
        "artifacts": {name: str(path) for name, path in written.items()},
        "warnings": validation_payload["warnings"],
        "errors": validation_payload["errors"],
        "strategy_enabled": bool((candidate_config.get("strategy") or {}).get("enabled")),
        "live_trading": validation_payload["live_trading"],
        "diff_changed_fields": len(diff_payload.get("changed_fields") or []),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a crypto config promotion proposal from experiment artifacts.")
    parser.add_argument("--experiment-dir", required=True)
    parser.add_argument("--current-config")
    parser.add_argument("--output-dir")
    parser.add_argument("--config-id")
    parser.add_argument("--use-best-eligible", action="store_true")
    parser.add_argument("--paper-forward-enable", action="store_true")
    return parser


def _default_output_dir(experiment_dir: Path) -> Path:
    experiment_name = experiment_dir.name
    if experiment_dir.parent.name == "experiments":
        return experiment_dir.parent.parent / "config_promotions" / experiment_name
    return experiment_dir / "config_promotions" / experiment_name


def _flag(name: str) -> bool:
    value = str(os.getenv(name) or "").strip().lower()
    return value in {"1", "true", "yes", "y", "si", "s"}


def main() -> None:
    args = build_parser().parse_args()
    result = run_propose_crypto_config_promotion(
        experiment_dir=args.experiment_dir,
        current_config=args.current_config,
        output_dir=args.output_dir,
        config_id=args.config_id,
        use_best_eligible=args.use_best_eligible,
        paper_forward_enable=args.paper_forward_enable,
    )
    print("[CRYPTO-CONFIG-PROMOTION-PROPOSAL]")
    print(f"- status: {result['status']}")
    if result["status"] == "SUCCESS":
        print(f"- selected_config_id: {result['selected_config_id']}")
        print(f"- eligible_for_candidate: {result['eligible_for_candidate']}")
        print(f"- output_dir: {result['output_dir']}")
    else:
        print(f"- reason: {result.get('reason')}")


if __name__ == "__main__":
    main()
