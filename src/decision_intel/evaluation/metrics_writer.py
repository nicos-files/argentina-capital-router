from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Tuple

from src.decision_intel.contracts.evaluation.metrics_constants import (
    EVAL_ARTIFACT_NAME,
    EVAL_ARTIFACT_TYPE,
    HORIZON_ENUM,
    READER_MIN_VERSION,
    SCHEMA_VERSION,
)
from src.decision_intel.utils.io import ensure_run_dir, validate_run_write_path


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_evaluation_metrics(
    run_id: str,
    strategy_id: str,
    variant_id: str | None,
    horizon: str,
    metrics: Dict[str, float],
    base_path: str = "runs",
    content_hash: str | None = None,
) -> Tuple[Path, Dict[str, Any]]:
    if horizon not in HORIZON_ENUM:
        raise ValueError("horizon must be one of SHORT, MEDIUM, LONG")
    ensure_run_dir(run_id, base_path=base_path)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "reader_min_version": READER_MIN_VERSION,
        "run_id": run_id,
        "strategy_id": strategy_id,
        "variant_id": variant_id,
        "horizon": horizon,
        "metrics": metrics,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if content_hash is None:
        content_hash = _hash_text(serialized)

    output_path = validate_run_write_path(
        run_id,
        Path(base_path) / run_id / "artifacts" / f"evaluation.metrics.v{SCHEMA_VERSION}.json",
        base_path=base_path,
    )
    output_path.write_text(serialized, encoding="utf-8")

    manifest_entry = {
        "name": EVAL_ARTIFACT_NAME,
        "type": EVAL_ARTIFACT_TYPE,
        "path": output_path.as_posix(),
        "schema_version": SCHEMA_VERSION,
        "content_hash": content_hash,
    }
    return output_path, manifest_entry
