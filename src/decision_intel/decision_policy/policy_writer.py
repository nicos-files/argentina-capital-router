from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Tuple

from src.decision_intel.contracts.decision_policy.policy_constants import (
    POLICY_ARTIFACT_NAME,
    POLICY_ARTIFACT_TYPE,
    SCHEMA_VERSION,
)
from src.decision_intel.decision_policy.policy_validator import validate_policy_data
from src.decision_intel.utils.io import ensure_run_dir, validate_run_write_path


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_policy(
    run_id: str,
    policy: Dict[str, Any],
    base_path: str = "runs",
    content_hash: str | None = None,
) -> Tuple[Path, Dict[str, Any]]:
    ensure_run_dir(run_id, base_path=base_path)
    # validate_policy_data enforces schema_version and reader_min_version.
    validate_policy_data(policy)
    serialized = json.dumps(policy, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if content_hash is None:
        content_hash = _hash_text(serialized)

    output_path = validate_run_write_path(
        run_id,
        Path(base_path) / run_id / "artifacts" / f"evaluation.policy.v{SCHEMA_VERSION}.json",
        base_path=base_path,
    )
    output_path.write_text(serialized, encoding="utf-8")

    manifest_entry = {
        "name": POLICY_ARTIFACT_NAME,
        "type": POLICY_ARTIFACT_TYPE,
        "path": str(output_path),
        "schema_version": SCHEMA_VERSION,
        "content_hash": content_hash,
    }
    return output_path, manifest_entry
