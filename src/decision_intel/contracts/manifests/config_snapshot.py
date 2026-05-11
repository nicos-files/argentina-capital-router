from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from src.decision_intel.contracts.metadata_models import CURRENT_SCHEMA_VERSION, RunStatus
from src.decision_intel.utils.io import ensure_run_dir, validate_run_write_path


class MissingDataSnapshotIdsError(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def write_config_snapshot(
    run_id: str,
    config: Dict[str, Any],
    base_path: str = "runs",
    schema_version: str = CURRENT_SCHEMA_VERSION,
) -> Path:
    run_root = ensure_run_dir(run_id, base_path=base_path)
    filename = f"config.snapshot.v{schema_version}.json"
    snapshot_path = validate_run_write_path(
        run_id,
        run_root / "manifests" / filename,
        base_path=base_path,
    )
    payload = json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    snapshot_path.write_text(payload, encoding="utf-8")
    return snapshot_path


def apply_config_snapshot_to_manifest(manifest: Dict[str, Any], snapshot_path: Path) -> Dict[str, Any]:
    manifest.setdefault("config", {})
    manifest["config"]["snapshot_path"] = str(snapshot_path)
    return manifest


def require_data_snapshot_ids(
    manifest: Dict[str, Any],
    data_snapshot_ids: Dict[str, str],
    error_code: str = "MISSING_DATA_SNAPSHOT_IDS",
) -> None:
    if not data_snapshot_ids:
        message = "data_snapshot_ids must be provided for deterministic runs"
        manifest["status"] = RunStatus.FAILED.value
        manifest["error"] = {"error_code": error_code, "message": message}
        raise MissingDataSnapshotIdsError(error_code, message)
    manifest["data_snapshot_ids"] = data_snapshot_ids
