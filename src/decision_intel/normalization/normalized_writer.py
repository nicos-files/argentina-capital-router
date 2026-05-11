from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Tuple

from src.decision_intel.contracts.normalization.normalization_constants import (
    NORMALIZED_ARTIFACT_NAME,
    NORMALIZED_ARTIFACT_TYPE,
    READER_MIN_VERSION,
    SCHEMA_VERSION,
)
from src.decision_intel.normalization.normalizer import NormalizationResult
from src.decision_intel.utils.io import ensure_run_dir, validate_run_write_path


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_normalized_metrics(
    run_id: str,
    strategy_id: str,
    variant_id: str | None,
    result: NormalizationResult,
    base_path: str = "runs",
    content_hash: str | None = None,
) -> Tuple[Path, Dict[str, Any]]:
    ensure_run_dir(run_id, base_path=base_path)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "reader_min_version": READER_MIN_VERSION,
        "run_id": run_id,
        "strategy_id": strategy_id,
        "variant_id": variant_id,
        "normalization": {"method": result.method, "params": result.params},
        "metrics_by_horizon": result.metrics_by_horizon,
        "normalized_metrics": result.normalized_metrics,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if content_hash is None:
        content_hash = _hash_text(serialized)

    output_path = validate_run_write_path(
        run_id,
        Path(base_path) / run_id / "artifacts" / f"evaluation.normalized.v{SCHEMA_VERSION}.json",
        base_path=base_path,
    )
    output_path.write_text(serialized, encoding="utf-8")

    manifest_entry = {
        "name": NORMALIZED_ARTIFACT_NAME,
        "type": NORMALIZED_ARTIFACT_TYPE,
        "path": str(output_path),
        "schema_version": SCHEMA_VERSION,
        "content_hash": content_hash,
    }
    return output_path, manifest_entry
