from __future__ import annotations

import json
import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

from src.decision_intel.contracts.metadata_models import RunStatus


class GuardrailViolation(Exception):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _canonical_json(data: Dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_config_snapshot_immutable(
    manifest: Dict[str, Any],
    snapshot_path: Path,
    expected_hash: str | None,
    error_code: str = "CONFIG_SNAPSHOT_MUTATED",
) -> None:
    payload = snapshot_path.read_text(encoding="utf-8")
    actual_hash = _hash_text(payload)
    if expected_hash and actual_hash != expected_hash:
        manifest["status"] = RunStatus.FAILED.value
        manifest.setdefault("skips", []).append(
            {"code": error_code, "reason": "config snapshot hash mismatch"}
        )
        raise GuardrailViolation(error_code, "config snapshot hash mismatch")


def require_data_snapshot_ids_stable(
    manifest: Dict[str, Any],
    data_snapshot_ids: Dict[str, str],
    error_code: str = "MISSING_DATA_SNAPSHOT_IDS",
) -> None:
    if not data_snapshot_ids:
        manifest["status"] = RunStatus.FAILED.value
        manifest.setdefault("skips", []).append(
            {"code": error_code, "reason": "data_snapshot_ids missing or empty"}
        )
        raise GuardrailViolation(error_code, "data_snapshot_ids missing or empty")
    manifest["data_snapshot_ids"] = data_snapshot_ids


def compare_decision_outputs(
    baseline: Iterable[Dict[str, Any]],
    candidate: Iterable[Dict[str, Any]],
) -> bool:
    """
    Compare decision outputs for functional equivalence. Caller must opt in.
    """
    def normalize(rows: Iterable[Dict[str, Any]]) -> List[str]:
        return sorted(_hash_text(_canonical_json(r)) for r in rows)

    return normalize(baseline) == normalize(candidate)
