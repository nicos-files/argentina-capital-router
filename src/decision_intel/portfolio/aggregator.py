from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from src.decision_intel.contracts.metadata_models import CURRENT_SCHEMA_VERSION, MIN_READER_VERSION
from src.decision_intel.utils.io import ensure_run_dir, validate_run_write_path


def aggregate_portfolio(
    run_id: str,
    weights: Dict[str, float],
    base_path: str = "runs",
) -> Tuple[Path, Dict[str, Any]]:
    run_root = ensure_run_dir(run_id, base_path=base_path)
    manifest_path = run_root / "manifests" / f"run_manifest.v{CURRENT_SCHEMA_VERSION}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    decision_path = _find_artifact_path(run_root, manifest, "decision.outputs")
    decision_payload = json.loads(Path(decision_path).read_text(encoding="utf-8"))

    decisions = decision_payload.get("decisions", [])
    positions: List[Dict[str, Any]] = []
    missing_weights: List[str] = []
    total_weight = 0.0
    total_weighted_signal = 0.0

    for item in sorted(decisions, key=lambda row: row.get("asset_id", "")):
        asset_id = item.get("asset_id")
        signal = item.get("signal")
        weight = weights.get(asset_id)
        weighted_signal = None
        if weight is None:
            if isinstance(asset_id, str) and asset_id:
                missing_weights.append(asset_id)
        else:
            weighted_signal = signal * weight
            total_weight += weight
            total_weighted_signal += weighted_signal
        positions.append(
            {
                "asset_id": asset_id,
                "signal": signal,
                "weight": weight,
                "weighted_signal": weighted_signal,
            }
        )

    missing_weights = sorted(set(missing_weights))
    payload = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "reader_min_version": MIN_READER_VERSION,
        "run_id": run_id,
        "source_artifact": "decision.outputs",
        "positions": positions,
        "missing_weights": missing_weights,
        "total_weight": total_weight,
        "total_weighted_signal": total_weighted_signal,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    output_path = validate_run_write_path(
        run_id,
        run_root / "artifacts" / "portfolio" / f"portfolio.aggregation.v{CURRENT_SCHEMA_VERSION}.json",
        base_path=base_path,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(serialized, encoding="utf-8")

    entry = {
        "name": "portfolio.aggregation",
        "type": "portfolio.aggregation",
        "path": output_path.relative_to(run_root).as_posix(),
        "schema_version": CURRENT_SCHEMA_VERSION,
        "content_hash": _hash_text(serialized),
    }

    manifest.setdefault("artifact_index", [])
    _upsert_artifact(manifest["artifact_index"], entry)
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )
    return output_path, entry


def _find_artifact_path(run_root: Path, manifest: Dict[str, Any], name: str) -> str:
    for entry in manifest.get("artifact_index", []):
        if entry.get("name") == name:
            path_value = entry.get("path")
            if not path_value:
                raise ValueError(f"artifact {name} path missing in manifest")
            path = Path(path_value)
            return str(path if path.is_absolute() else run_root / path)
    raise ValueError(f"artifact {name} not found in manifest")


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _has_artifact(artifact_index: List[Dict[str, Any]], candidate: Dict[str, Any]) -> bool:
    for entry in artifact_index:
        if (
            entry.get("name") == candidate["name"]
            and entry.get("type") == candidate["type"]
            and entry.get("path") == candidate["path"]
        ):
            return True
    return False


def _upsert_artifact(artifact_index: List[Dict[str, Any]], candidate: Dict[str, Any]) -> None:
    for index, entry in enumerate(artifact_index):
        if (
            entry.get("name") == candidate["name"]
            and entry.get("type") == candidate["type"]
            and entry.get("path") == candidate["path"]
        ):
            artifact_index[index] = {**entry, **candidate}
            return
    artifact_index.append(candidate)
