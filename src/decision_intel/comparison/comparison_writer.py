from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Tuple

from src.decision_intel.comparison.comparator import ComparisonResult
from src.decision_intel.contracts.comparison.comparison_constants import (
    COMPARISON_ARTIFACT_NAME,
    COMPARISON_ARTIFACT_TYPE,
    READER_MIN_VERSION,
    SCHEMA_VERSION,
)
from src.decision_intel.utils.io import ensure_run_dir, validate_run_write_path


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_comparison(
    run_id: str,
    baseline: Dict[str, Any],
    candidate: Dict[str, Any],
    result: ComparisonResult,
    base_path: str = "runs",
    content_hash: str | None = None,
) -> Tuple[Path, Dict[str, Any]]:
    ensure_run_dir(run_id, base_path=base_path)
    comparison_metrics: Dict[str, Any] = {}
    for key in result.deltas.keys():
        comparison_metrics[key] = {
            "baseline": result.baseline_metrics.get(key),
            "candidate": result.candidate_metrics.get(key),
            "delta": result.deltas.get(key),
        }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "reader_min_version": READER_MIN_VERSION,
        "run_id": run_id,
        "baseline": baseline,
        "candidate": candidate,
        "comparison_metrics": comparison_metrics,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if content_hash is None:
        content_hash = _hash_text(serialized)

    output_path = validate_run_write_path(
        run_id,
        Path(base_path) / run_id / "artifacts" / f"evaluation.comparison.v{SCHEMA_VERSION}.json",
        base_path=base_path,
    )
    output_path.write_text(serialized, encoding="utf-8")

    manifest_entry = {
        "name": COMPARISON_ARTIFACT_NAME,
        "type": COMPARISON_ARTIFACT_TYPE,
        "path": str(output_path),
        "schema_version": SCHEMA_VERSION,
        "content_hash": content_hash,
    }
    return output_path, manifest_entry
