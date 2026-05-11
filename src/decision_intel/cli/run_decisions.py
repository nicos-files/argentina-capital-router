from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from src.decision_intel.contracts.manifests.config_snapshot import (
    apply_config_snapshot_to_manifest,
    require_data_snapshot_ids,
    write_config_snapshot,
)
from src.decision_intel.contracts.manifests.run_manifest_writer import (
    append_manifest_artifact,
    initialize_manifest,
    persist_manifest,
    update_manifest_data_snapshot_ids,
    update_manifest_status,
)
from src.decision_intel.contracts.metadata_models import RunStatus
from src.decision_intel.contracts.signals.signal_loader import append_signal_artifact, load_signal_input
from src.decision_intel.contracts.strategies.strategy_loader import load_strategy_config
from src.decision_intel.decision.engine import run_decision_engine
from src.decision_intel.decision.output_writer import write_decision_outputs
from src.decision_intel.decision.rules.registry import RuleRegistry
from src.decision_intel.decision.rules.builtin import (
    constraint_max_positions,
    filter_min_liquidity,
    sizing_fixed,
)
from src.decision_intel.utils.io import ensure_run_dir


def _load_json(path: str | Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run decision-only pipeline")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--strategy-config", required=True)
    parser.add_argument("--signals", required=True)
    parser.add_argument("--data-snapshot-id", action="append", default=[])
    parser.add_argument("--base-path", default="runs")
    args = parser.parse_args()

    ensure_run_dir(args.run_id, base_path=args.base_path)
    manifest: Dict[str, Any] = {"artifact_index": [], "skips": []}
    run_manifest = None

    try:
        config_snapshot = write_config_snapshot(args.run_id, _load_json(args.strategy_config), base_path=args.base_path)
        apply_config_snapshot_to_manifest(manifest, config_snapshot)
        run_manifest = initialize_manifest(args.run_id, str(config_snapshot))
        run_manifest = update_manifest_status(run_manifest, RunStatus.RUNNING)
        persist_manifest(args.run_id, run_manifest, base_path=args.base_path)

        strategy = load_strategy_config(args.strategy_config)
        signals = load_signal_input(args.signals)

        data_snapshot_ids = {f"snapshot_{i}": v for i, v in enumerate(args.data_snapshot_id)}
        require_data_snapshot_ids(manifest, data_snapshot_ids)
        run_manifest = update_manifest_data_snapshot_ids(run_manifest, data_snapshot_ids)

        append_signal_artifact(manifest, args.signals)

        registry = RuleRegistry()
        registry.register_sizing("size.fixed", sizing_fixed)
        registry.register_constraint("risk.max_positions", constraint_max_positions)
        registry.register_filter("eligibility.liquid", filter_min_liquidity)

        rules = registry.resolve(
            sizing_rule=strategy.rules.sizing_rule,
            constraints=strategy.rules.constraints,
            filters=strategy.rules.filters,
        )

        decisions = run_decision_engine(
            strategy=strategy,
            signals=signals["signals"],
            rules=rules,
            rule_configs={"sizing_rule": {}, "constraints": {}, "filters": {}},
        )

        output_path, decision_entry = write_decision_outputs(
            run_id=args.run_id,
            decisions=[d.__dict__ for d in decisions],
            strategy_id=strategy.strategy_id,
            variant_id=strategy.variant_id,
            horizon=strategy.horizon,
            rule_refs={
                "sizing_rule": strategy.rules.sizing_rule,
                "constraints": strategy.rules.constraints,
                "filters": strategy.rules.filters,
            },
            config_snapshot_path=str(config_snapshot),
            base_path=args.base_path,
        )

        # update manifest with artifacts and finalize
        run_manifest = append_manifest_artifact(run_manifest, manifest["artifact_index"][0])
        run_manifest = append_manifest_artifact(run_manifest, decision_entry)
        run_manifest = update_manifest_status(run_manifest, RunStatus.SUCCESS)
        persist_manifest(args.run_id, run_manifest, base_path=args.base_path)
    except Exception:
        # best-effort failure status
        try:
            if run_manifest is not None:
                run_manifest = update_manifest_status(run_manifest, RunStatus.FAILED)
                persist_manifest(args.run_id, run_manifest, base_path=args.base_path)
        finally:
            raise


if __name__ == "__main__":
    main()
