from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Tuple

from src.decision_intel.contracts.decisions.decision_constants import DECISION_ARTIFACT_NAME
from src.decision_intel.contracts.metadata_models import CURRENT_SCHEMA_VERSION, MIN_READER_VERSION
from src.decision_intel.evaluation.metrics_writer import write_evaluation_metrics
from src.decision_intel.utils.io import validate_run_write_path


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _derive_run_context(manifest_path: Path) -> Tuple[Path, str]:
    if not manifest_path.name.startswith("run_manifest.v") or not manifest_path.name.endswith(".json"):
        raise ValueError("manifest_path must be a run_manifest.v*.json file")
    run_id = manifest_path.parents[1].name
    base_path = manifest_path.parents[2]
    return base_path, run_id


def _load_manifest_schema_required() -> set[str]:
    schema_path = Path("src/decision_intel/contracts/manifests/run_manifest.schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return set(schema["required"])


def _validate_manifest_contract(manifest: Dict[str, Any], run_id: str) -> None:
    required = _load_manifest_schema_required()
    missing = required.difference(manifest.keys())
    if missing:
        raise ValueError(f"manifest missing required fields: {sorted(missing)}")
    if manifest["schema_version"] != CURRENT_SCHEMA_VERSION:
        raise ValueError("manifest schema_version mismatch")
    if manifest["reader_min_version"] != MIN_READER_VERSION:
        raise ValueError("manifest reader_min_version mismatch")
    if manifest["run_id"] != run_id:
        raise ValueError("manifest run_id does not match path")
    if "created_at" not in manifest["timestamps"]:
        raise ValueError("manifest timestamps.created_at is required")
    if "snapshot_path" not in manifest["config"]:
        raise ValueError("manifest config.snapshot_path is required")
    for entry in manifest.get("artifact_index", []):
        for key in ("name", "type", "path", "schema_version"):
            if key not in entry:
                raise ValueError("artifact_index entries must include name, type, path, schema_version")


def _find_decision_artifact(manifest: Dict[str, Any]) -> str:
    for entry in manifest.get("artifact_index", []):
        if entry.get("name") == DECISION_ARTIFACT_NAME:
            return entry["path"]
    raise ValueError("decision.outputs artifact not found in manifest")


def compute_metrics_from_decisions(decisions: list[Dict[str, Any]]) -> Dict[str, float]:
    count = len(decisions)
    if count == 0:
        return {"decision_count": 0, "avg_signal": 0.0}
    avg_signal = sum(d["signal"] for d in decisions) / count
    return {"decision_count": float(count), "avg_signal": avg_signal}


def run_evaluation_from_manifest(manifest_path: str | Path) -> Path:
    manifest_file = Path(manifest_path)
    base_path, run_id = _derive_run_context(manifest_file)
    manifest = _load_json(manifest_file)
    _validate_manifest_contract(manifest, run_id)
    decision_path = Path(_find_decision_artifact(manifest))
    decision_payload = _load_json(decision_path)
    metrics = compute_metrics_from_decisions(decision_payload["decisions"])

    output_path, entry = write_evaluation_metrics(
        run_id=decision_payload["run_id"],
        strategy_id=decision_payload["strategy_id"],
        variant_id=decision_payload.get("variant_id"),
        horizon=decision_payload["horizon"],
        metrics=metrics,
        base_path=base_path,
    )

    manifest.setdefault("artifact_index", []).append(entry)
    manifest_out = validate_run_write_path(
        run_id,
        manifest_file,
        base_path=base_path,
    )
    manifest_out.write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    return output_path
