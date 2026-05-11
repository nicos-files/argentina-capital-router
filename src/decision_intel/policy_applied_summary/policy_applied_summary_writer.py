from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Tuple

from src.decision_intel.contracts.policy_applied_summary.policy_applied_summary_constants import (
    POLICY_APPLIED_SUMMARY_ARTIFACT_NAME,
    POLICY_APPLIED_SUMMARY_ARTIFACT_TYPE,
    READER_MIN_VERSION,
    SCHEMA_VERSION,
)
from src.decision_intel.policy_applied_summary.summarizer import summarize_policy_applied
from src.decision_intel.utils.io import ensure_run_dir, validate_run_write_path


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_policy_applied_summary(
    run_id: str,
    policy_id: str,
    baseline: Dict[str, Any],
    candidate: Dict[str, Any],
    policy_applied_metrics: Dict[str, Dict[str, Any]],
    base_path: str = "runs",
    content_hash: str | None = None,
) -> Tuple[Path, Dict[str, Any]]:
    ensure_run_dir(run_id, base_path=base_path)
    summary = summarize_policy_applied(policy_applied_metrics)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "reader_min_version": READER_MIN_VERSION,
        "run_id": run_id,
        "policy_id": policy_id,
        "baseline": baseline,
        "candidate": candidate,
        "summary": {
            "total_policy_metrics": summary.total_policy_metrics,
            "metrics_with_null_delta": summary.metrics_with_null_delta,
            "metrics_with_non_null_delta": summary.metrics_with_non_null_delta,
            "thresholds_defined_count": summary.thresholds_defined_count,
            "thresholds_met_count": summary.thresholds_met_count,
            "thresholds_failed_count": summary.thresholds_failed_count,
            "thresholds_unknown_count": summary.thresholds_unknown_count,
            "oriented_delta_positive_count": summary.oriented_delta_positive_count,
            "oriented_delta_negative_count": summary.oriented_delta_negative_count,
            "oriented_delta_zero_count": summary.oriented_delta_zero_count,
            "oriented_delta_null_count": summary.oriented_delta_null_count,
            "null_delta_metrics": summary.null_delta_metrics,
            "thresholds_failed_metrics": summary.thresholds_failed_metrics,
            "thresholds_unknown_metrics": summary.thresholds_unknown_metrics,
        },
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if content_hash is None:
        content_hash = _hash_text(serialized)

    output_path = validate_run_write_path(
        run_id,
        Path(base_path) / run_id / "artifacts" / f"evaluation.policy_applied_summary.v{SCHEMA_VERSION}.json",
        base_path=base_path,
    )
    output_path.write_text(serialized, encoding="utf-8")

    manifest_entry = {
        "name": POLICY_APPLIED_SUMMARY_ARTIFACT_NAME,
        "type": POLICY_APPLIED_SUMMARY_ARTIFACT_TYPE,
        "path": str(output_path),
        "schema_version": SCHEMA_VERSION,
        "content_hash": content_hash,
    }
    return output_path, manifest_entry
