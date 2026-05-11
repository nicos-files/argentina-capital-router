from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Tuple

from src.decision_intel.contracts.policy_applied.policy_applied_constants import (
    POLICY_APPLIED_ARTIFACT_NAME,
    POLICY_APPLIED_ARTIFACT_TYPE,
    READER_MIN_VERSION,
    SCHEMA_VERSION,
)
from src.decision_intel.policy_applied.evaluator import apply_policy_to_comparison
from src.decision_intel.utils.io import ensure_run_dir, validate_run_write_path


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_policy_applied(
    run_id: str,
    baseline: Dict[str, Any],
    candidate: Dict[str, Any],
    policy: Dict[str, Any],
    comparison_metrics: Dict[str, Dict[str, Any]],
    base_path: str = "runs",
    content_hash: str | None = None,
) -> Tuple[Path, Dict[str, Any]]:
    ensure_run_dir(run_id, base_path=base_path)
    result = apply_policy_to_comparison(policy, comparison_metrics)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "reader_min_version": READER_MIN_VERSION,
        "run_id": run_id,
        "policy_id": result.policy_id,
        "baseline": baseline,
        "candidate": candidate,
        "policy_applied_metrics": result.applied_metrics,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if content_hash is None:
        content_hash = _hash_text(serialized)

    output_path = validate_run_write_path(
        run_id,
        Path(base_path) / run_id / "artifacts" / f"evaluation.policy_applied.v{SCHEMA_VERSION}.json",
        base_path=base_path,
    )
    output_path.write_text(serialized, encoding="utf-8")

    manifest_entry = {
        "name": POLICY_APPLIED_ARTIFACT_NAME,
        "type": POLICY_APPLIED_ARTIFACT_TYPE,
        "path": str(output_path),
        "schema_version": SCHEMA_VERSION,
        "content_hash": content_hash,
    }
    return output_path, manifest_entry
