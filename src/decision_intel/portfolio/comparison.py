from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from src.decision_intel.contracts.metadata_models import CURRENT_SCHEMA_VERSION, MIN_READER_VERSION
from src.decision_intel.utils.io import ensure_run_dir, validate_run_write_path


def compare_portfolio(run_id: str, base_path: str = "runs") -> Tuple[Path, Dict[str, Any]]:
    run_root = ensure_run_dir(run_id, base_path=base_path)
    manifest_path = run_root / "manifests" / f"run_manifest.v{CURRENT_SCHEMA_VERSION}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    decision_path = _find_artifact_path(run_root, manifest, "decision.outputs")
    aggregation_path = _find_artifact_path(run_root, manifest, "portfolio.aggregation")
    decision_payload = json.loads(Path(decision_path).read_text(encoding="utf-8"))
    aggregation_payload = json.loads(Path(aggregation_path).read_text(encoding="utf-8"))

    decisions = decision_payload.get("decisions", [])
    positions = aggregation_payload.get("positions", [])

    decisions_by_asset = {
        item.get("asset_id"): item
        for item in decisions
        if isinstance(item.get("asset_id"), str) and item.get("asset_id")
    }
    positions_by_asset = {
        item.get("asset_id"): item
        for item in positions
        if isinstance(item.get("asset_id"), str) and item.get("asset_id")
    }

    by_asset: List[Dict[str, Any]] = []
    for asset_id in sorted(set(decisions_by_asset.keys()) | set(positions_by_asset.keys())):
        decision = decisions_by_asset.get(asset_id, {})
        position = positions_by_asset.get(asset_id, {})
        signal = decision.get("signal")
        weight = position.get("weight")
        weighted_signal = position.get("weighted_signal")
        delta_weighted_signal = None
        if _is_number(weight) and _is_number(signal) and _is_number(weighted_signal):
            delta_weighted_signal = weighted_signal - (signal * weight)
        by_asset.append(
            {
                "asset_id": asset_id,
                "signal": signal,
                "weight": weight,
                "weighted_signal": weighted_signal,
                "delta_weighted_signal": delta_weighted_signal,
            }
        )

    missing_in_weights = [
        asset_id
        for asset_id in aggregation_payload.get("missing_weights", [])
        if isinstance(asset_id, str) and asset_id
    ]
    missing_in_weights = sorted(set(missing_in_weights))

    missing_in_decisions = [
        asset_id
        for asset_id in positions_by_asset.keys()
        if asset_id not in decisions_by_asset
    ]
    missing_in_decisions = sorted(set(missing_in_decisions))

    payload = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "reader_min_version": MIN_READER_VERSION,
        "run_id": run_id,
        "source_artifacts": ["decision.outputs", "portfolio.aggregation"],
        "by_asset": by_asset,
        "missing_in_weights": missing_in_weights,
        "missing_in_decisions": missing_in_decisions,
        "total_weight": aggregation_payload.get("total_weight", 0.0),
        "total_weighted_signal": aggregation_payload.get("total_weighted_signal", 0.0),
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    output_path = validate_run_write_path(
        run_id,
        run_root / "artifacts" / "portfolio" / f"portfolio.comparison.v{CURRENT_SCHEMA_VERSION}.json",
        base_path=base_path,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(serialized, encoding="utf-8")

    entry = {
        "name": "portfolio.comparison",
        "type": "portfolio.comparison",
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


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


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
