from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from src.decision_intel.contracts.metadata_models import (
    CURRENT_SCHEMA_VERSION,
    MIN_READER_VERSION,
    ConfigRef,
    ManifestTimestamps,
    RunManifest,
    RunStatus,
)
from src.decision_intel.utils.io import ensure_run_dir, validate_run_write_path


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def initialize_manifest(run_id: str, config_snapshot_path: str) -> RunManifest:
    return RunManifest(
        schema_version=CURRENT_SCHEMA_VERSION,
        reader_min_version=MIN_READER_VERSION,
        run_id=run_id,
        status=RunStatus.CREATED,
        timestamps=ManifestTimestamps(created_at=_utc_now_iso()),
        config=ConfigRef(snapshot_path=config_snapshot_path),
    )


def update_manifest_status(manifest: RunManifest, status: RunStatus) -> RunManifest:
    ts = manifest.timestamps
    started_at = ts.started_at or (_utc_now_iso() if status == RunStatus.RUNNING else None)
    completed_at = ts.completed_at or (
        _utc_now_iso() if status in (RunStatus.SUCCESS, RunStatus.FAILED, RunStatus.PARTIAL, RunStatus.SKIPPED) else None
    )
    return replace(
        manifest,
        status=status,
        timestamps=ManifestTimestamps(
            created_at=ts.created_at,
            started_at=started_at or ts.started_at,
            completed_at=completed_at or ts.completed_at,
        ),
    )


def update_manifest_data_snapshot_ids(manifest: RunManifest, data_snapshot_ids: Dict[str, str]) -> RunManifest:
    return replace(manifest, data_snapshot_ids=data_snapshot_ids)


def append_manifest_artifact(manifest: RunManifest, artifact: Dict[str, Any]) -> RunManifest:
    return replace(manifest, artifact_index=[*manifest.artifact_index, artifact])


def update_manifest_error(manifest: RunManifest, code: str, message: str) -> RunManifest:
    return replace(manifest, error={"error_code": code, "message": message})


def persist_manifest(run_id: str, manifest: RunManifest, base_path: str = "runs") -> Path:
    run_root = ensure_run_dir(run_id, base_path=base_path)
    manifest_path = validate_run_write_path(
        run_id,
        run_root / "manifests" / f"run_manifest.v{CURRENT_SCHEMA_VERSION}.json",
        base_path=base_path,
    )
    manifest_dict: Dict[str, Any] = asdict(manifest)
    manifest_dict["status"] = manifest.status.value
    manifest_path.write_text(json.dumps(manifest_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    return manifest_path
