from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.decision_intel.contracts.decisions.decision_constants import DECISION_ARTIFACT_NAME
from src.decision_intel.contracts.metadata_models import CURRENT_SCHEMA_VERSION, MIN_READER_VERSION
from src.decision_intel.contracts.signals.signal_constants import SIGNAL_ARTIFACT_NAME
from src.decision_intel.contracts.strategies.strategy_loader import load_strategy_config
from src.decision_intel.contracts.signals.signal_loader import load_signal_input
from src.decision_intel.decision.engine import run_decision_engine
from src.decision_intel.decision.output_writer import write_decision_outputs
from src.decision_intel.decision.rules.builtin import (
    constraint_max_positions,
    filter_min_liquidity,
    sizing_fixed,
)
from src.decision_intel.decision.rules.registry import RuleRegistry


@dataclass(frozen=True)
class ReplayArtifactResult:
    name: str
    original_path: str
    replay_path: str
    result: str
    differences: List[str]


@dataclass(frozen=True)
class ReplayReport:
    match_status: str
    compared_artifacts: List[str]
    results: List[ReplayArtifactResult]
    report_path: str


def replay_run(
    run_id: str,
    base_path: str = "runs",
    replay_id: Optional[str] = None,
) -> ReplayReport:
    manifest_path = _manifest_path(run_id, base_path=base_path)
    manifest = _load_manifest(manifest_path)
    run_root = Path(base_path) / run_id
    base_root = Path(base_path)
    config_snapshot_path = _resolve_manifest_path(run_root, _config_snapshot_path(manifest), base_root)
    strategy = load_strategy_config(config_snapshot_path)
    signals_path = _resolve_manifest_path(run_root, _find_artifact_path(manifest, SIGNAL_ARTIFACT_NAME), base_root)
    if not Path(signals_path).exists():
        raise ValueError(f"signals.input path does not exist: {signals_path}")
    signals = load_signal_input(signals_path)
    decision_path = _resolve_manifest_path(run_root, _find_artifact_path(manifest, DECISION_ARTIFACT_NAME), base_root)
    if not Path(decision_path).exists():
        raise ValueError(f"decision.outputs path does not exist: {decision_path}")
    decision_payload = _load_json(decision_path)
    rule_refs = manifest.get("rule_refs") if isinstance(manifest.get("rule_refs"), dict) else decision_payload.get("rule_refs", {})
    rule_configs = decision_payload.get("rule_configs", {"sizing_rule": {}, "constraints": {}, "filters": {}})

    registry = RuleRegistry()
    registry.register_sizing("size.fixed", sizing_fixed)
    registry.register_constraint("risk.max_positions", constraint_max_positions)
    registry.register_filter("eligibility.liquid", filter_min_liquidity)
    try:
        rules = registry.resolve(
            sizing_rule=rule_refs.get("sizing_rule"),
            constraints=rule_refs.get("constraints", []),
            filters=rule_refs.get("filters", []),
        )
    except (KeyError, ValueError) as exc:
        raise ValueError(f"unknown rule ref in historical run: {exc}") from exc

    decisions = run_decision_engine(
        strategy=strategy,
        signals=signals["signals"],
        rules=rules,
        rule_configs=rule_configs,
    )

    replay_root, replay_base, replay_run_id = _replay_root(run_id, base_path=base_path, replay_id=replay_id)
    replay_output_path, _ = write_decision_outputs(
        run_id=run_id,
        decisions=[d.__dict__ for d in decisions],
        strategy_id=strategy.strategy_id,
        variant_id=strategy.variant_id,
        horizon=strategy.horizon,
        rule_refs=rule_refs,
        config_snapshot_path=config_snapshot_path,
        base_path=str(replay_root),
    )

    replay_artifacts = {DECISION_ARTIFACT_NAME: str(replay_output_path)}
    results = _compare_manifest_artifacts(run_root, base_root, manifest, replay_artifacts)
    results = sorted(results, key=lambda item: item.name)
    match_status = "IDENTICAL" if all(r.result == "IDENTICAL" for r in results) else "DIFFERENT"
    report_path = replay_root / "replay.diff.json"
    report = ReplayReport(
        match_status=match_status,
        compared_artifacts=[result.name for result in results],
        results=results,
        report_path=str(report_path),
    )
    report_path.write_text(_serialize_report(report), encoding="utf-8")
    return report


def _manifest_path(run_id: str, base_path: str) -> Path:
    return Path(base_path) / run_id / "manifests" / f"run_manifest.v{CURRENT_SCHEMA_VERSION}.json"


def _load_manifest(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("manifest must be a JSON object")
    if data.get("schema_version") != CURRENT_SCHEMA_VERSION:
        raise ValueError("manifest schema_version mismatch")
    if data.get("reader_min_version") != MIN_READER_VERSION:
        raise ValueError("manifest reader_min_version mismatch")
    if "run_id" not in data:
        raise ValueError("manifest missing run_id")
    if "config" not in data or "snapshot_path" not in data["config"]:
        raise ValueError("manifest missing config.snapshot_path")
    if "artifact_index" not in data:
        raise ValueError("manifest missing artifact_index")
    return data


def _config_snapshot_path(manifest: Dict[str, Any]) -> str:
    return str(manifest["config"]["snapshot_path"])


def _find_artifact_path(manifest: Dict[str, Any], name: str) -> str:
    for entry in manifest.get("artifact_index", []):
        if entry.get("name") == name:
            return str(entry.get("path"))
    raise ValueError(f"artifact {name} not found in manifest")

def _replay_root(run_id: str, base_path: str, replay_id: Optional[str]) -> tuple[Path, str, str]:
    if replay_id is None:
        replay_id = datetime.now(timezone.utc).strftime("replay-%Y%m%dT%H%M%SZ")
    replay_base_root = Path(base_path) / "replays" / run_id
    replay_root = replay_base_root / replay_id
    replay_root.mkdir(parents=True, exist_ok=False)
    return replay_root, str(replay_base_root), replay_id


def _compare_manifest_artifacts(
    run_root: Path,
    base_root: Path,
    manifest: Dict[str, Any],
    replay_artifacts: Dict[str, str],
) -> List[ReplayArtifactResult]:
    results: List[ReplayArtifactResult] = []
    for entry in manifest.get("artifact_index", []):
        name = entry.get("name")
        if name == SIGNAL_ARTIFACT_NAME:
            continue
        if name not in replay_artifacts:
            continue
        original_path = _resolve_manifest_path(run_root, str(entry.get("path")), base_root)
        replay_path = replay_artifacts.get(name)
        results.append(_compare_artifacts(name, original_path, replay_path))
    return results


def _compare_artifacts(name: str, original_path: str, replay_path: Optional[str]) -> ReplayArtifactResult:
    differences: List[str] = []
    result = "IDENTICAL"
    if not Path(original_path).exists():
        differences.append("missing_original")
        result = "DIFFERENT"
    if replay_path is None or not Path(replay_path).exists():
        differences.append("missing_replay")
        result = "DIFFERENT"
    if result == "DIFFERENT":
        return ReplayArtifactResult(
            name=name,
            original_path=original_path,
            replay_path=replay_path or "",
            result=result,
            differences=differences,
        )
    if not _is_json_path(original_path):
        return ReplayArtifactResult(
            name=name,
            original_path=original_path,
            replay_path=replay_path,
            result="DIFFERENT",
            differences=["unsupported_format"],
        )
    try:
        original = _load_json(original_path)
        replayed = _load_json(replay_path)
    except json.JSONDecodeError:
        return ReplayArtifactResult(
            name=name,
            original_path=original_path,
            replay_path=replay_path,
            result="DIFFERENT",
            differences=["unsupported_format"],
        )
    differences = _diff_json(original, replayed)
    result = "IDENTICAL" if not differences else "DIFFERENT"
    return ReplayArtifactResult(
        name=name,
        original_path=original_path,
        replay_path=replay_path,
        result=result,
        differences=differences,
    )


def _diff_json(left: Any, right: Any, path: str = "") -> List[str]:
    if type(left) is not type(right):
        return [path or "/"]
    if isinstance(left, dict):
        diffs: List[str] = []
        for key in sorted(set(left.keys()) | set(right.keys())):
            next_path = f"{path}/{key}"
            if key not in left or key not in right:
                diffs.append(next_path)
                continue
            diffs.extend(_diff_json(left[key], right[key], next_path))
        return diffs
    if isinstance(left, list):
        diffs = []
        if len(left) != len(right):
            diffs.append(f"{path}/length")
        if len(left) > len(right):
            diffs.append(f"{path}/extra_left")
        if len(right) > len(left):
            diffs.append(f"{path}/extra_right")
        for index, (l_item, r_item) in enumerate(zip(left, right)):
            diffs.extend(_diff_json(l_item, r_item, f"{path}/{index}"))
        return diffs
    if left != right:
        return [path or "/"]
    return []


def _resolve_manifest_path(run_root: Path, value: str, base_root: Path) -> str:
    path = Path(value)
    if path.is_absolute():
        return str(path)
    run_relative = run_root / path
    if run_relative.exists():
        return str(run_relative)
    return str(base_root / path)


def _is_json_path(path: str) -> bool:
    return Path(path).suffix.lower() == ".json"


def _load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _serialize_report(report: ReplayReport) -> str:
    payload = {
        "match_status": report.match_status,
        "compared_artifacts": report.compared_artifacts,
        "results": [
            {
                "name": result.name,
                "original_path": result.original_path,
                "replay_path": result.replay_path,
                "result": result.result,
                "differences": result.differences,
            }
            for result in report.results
        ],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
