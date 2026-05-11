from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

from src.decision_intel.contracts.metadata_models import CURRENT_SCHEMA_VERSION

_NOTEBOOK_FORMATS = {
    "decision.outputs": "parquet",
    "evaluation.metrics": "csv",
    "evaluation.normalized": "json",
    "evaluation.comparison": "json",
    "evaluation.analysis_summary": "json",
    "evaluation.policy": "json",
    "evaluation.policy_applied": "json",
    "evaluation.policy_applied_summary": "json",
}
# Only decision.outputs and evaluation.metrics are notebook-friendly by design.
# JSON exports for other artifacts are convenience copies (no recomputation).


def export_notebook_artifacts(run_id: str, base_path: str = "runs") -> Path:
    run_root = Path(base_path) / run_id
    manifest_path = run_root / "manifests" / f"run_manifest.v{CURRENT_SCHEMA_VERSION}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifact_index: List[Dict[str, Any]] = manifest.get("artifact_index", [])

    export_root = run_root / "artifacts" / "notebook"
    export_root.mkdir(parents=True, exist_ok=True)
    export_entries: List[Dict[str, Any]] = []

    for entry in artifact_index:
        name = entry.get("name")
        if name not in _NOTEBOOK_FORMATS:
            continue
        fmt = _NOTEBOOK_FORMATS[name]
        source_path = _resolve_manifest_path(run_root, entry.get("path"))
        actual_format, actual_path = _export_with_format(fmt, name, source_path, export_root)
        export_entries.append(
            {
                "name": f"notebook.{name}",
                "type": f"notebook.{actual_format}",
                "path": actual_path.relative_to(run_root).as_posix(),
                "schema_version": CURRENT_SCHEMA_VERSION,
                "content_hash": _hash_file(actual_path),
            }
        )

    for export_entry in export_entries:
        if not _has_artifact(artifact_index, export_entry):
            artifact_index.append(export_entry)

    manifest["artifact_index"] = artifact_index
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )
    return manifest_path


def _resolve_manifest_path(run_root: Path, value: str | None) -> Path:
    if not value:
        raise ValueError("artifact path missing in manifest")
    path = Path(value)
    if path.is_absolute():
        return path
    return run_root / path


def _export_with_format(format_name: str, artifact_name: str, source_path: Path, export_root: Path) -> tuple[str, Path]:
    if format_name == "parquet":
        return _export_parquet(artifact_name, source_path, export_root)
    if format_name == "csv":
        target_path = export_root / f"{artifact_name}.csv"
        _export_csv(source_path, target_path)
        return "csv", target_path
    target_path = export_root / f"{artifact_name}.json"
    _export_json(source_path, target_path)
    return "json", target_path


def _export_parquet(artifact_name: str, source_path: Path, export_root: Path) -> tuple[str, Path]:
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    rows = payload.get("decisions", [])
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        target_path = export_root / f"{artifact_name}.csv"
        _export_decisions_csv(rows, target_path)
        return "csv", target_path
    target_path = export_root / f"{artifact_name}.parquet"
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, target_path)
    return "parquet", target_path


def _export_csv(source_path: Path, target_path: Path) -> None:
    import csv

    payload = json.loads(source_path.read_text(encoding="utf-8"))
    metrics = payload.get("metrics", {})
    rows = [
        {
            "metric": key,
            "value": metrics[key],
            "run_id": payload.get("run_id"),
            "strategy_id": payload.get("strategy_id"),
            "variant_id": payload.get("variant_id"),
            "horizon": payload.get("horizon"),
        }
        for key in sorted(metrics.keys())
    ]
    with target_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["metric", "value", "run_id", "strategy_id", "variant_id", "horizon"],
        )
        writer.writeheader()
        writer.writerows(rows)


def _export_decisions_csv(rows: List[Dict[str, Any]], target_path: Path) -> None:
    import csv

    fieldnames = sorted({key for row in rows for key in row.keys()})
    with target_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _export_json(source_path: Path, target_path: Path) -> None:
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    target_path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _has_artifact(artifact_index: List[Dict[str, Any]], candidate: Dict[str, Any]) -> bool:
    for entry in artifact_index:
        if (
            entry.get("name") == candidate["name"]
            and entry.get("type") == candidate["type"]
            and entry.get("path") == candidate["path"]
        ):
            return True
    return False
