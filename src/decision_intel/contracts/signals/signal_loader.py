from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any, Dict, List

from src.decision_intel.contracts.signals.signal_constants import (
    HORIZON_ENUM,
    READER_MIN_VERSION,
    SCHEMA_VERSION,
    SIGNAL_ARTIFACT_NAME,
    SIGNAL_ARTIFACT_TYPE,
)


class SignalInputError(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _require_field(obj: Dict[str, Any], field: str, error_code: str) -> Any:
    if field not in obj:
        raise SignalInputError(error_code, f"missing required field: {field}")
    return obj[field]


def _validate_schema(data: Dict[str, Any]) -> None:
    if data.get("schema_version") != SCHEMA_VERSION:
        raise SignalInputError("SCHEMA_VERSION_MISMATCH", "unsupported schema_version")
    if data.get("reader_min_version") != READER_MIN_VERSION:
        raise SignalInputError("READER_MIN_VERSION_MISMATCH", "unsupported reader_min_version")
    horizon = _require_field(data, "horizon", "MISSING_HORIZON")
    if horizon not in HORIZON_ENUM:
        raise SignalInputError("INVALID_HORIZON", "horizon must be one of SHORT, MEDIUM, LONG")
    signals = _require_field(data, "signals", "MISSING_SIGNALS")
    if not isinstance(signals, list):
        raise SignalInputError("INVALID_SIGNALS", "signals must be a list")
    for item in signals:
        if not isinstance(item, dict):
            raise SignalInputError("INVALID_SIGNAL_ROW", "signal entries must be objects")
        if "asset_id" not in item or "signal" not in item:
            raise SignalInputError("INVALID_SIGNAL_ROW", "signal entries require asset_id and signal")


def load_signal_input(path: str | Path) -> Dict[str, Any]:
    signal_path = Path(path)
    data = json.loads(signal_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SignalInputError("INVALID_SIGNAL_INPUT", "signal input must be a JSON object")
    _validate_schema(data)
    return data


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def append_signal_artifact(
    manifest: Dict[str, Any],
    path: str | Path,
    content_hash: str | None = None,
) -> Dict[str, Any]:
    signal_path = Path(path)
    if content_hash is None:
        content_hash = _hash_file(signal_path)
    entry = {
        "name": SIGNAL_ARTIFACT_NAME,
        "type": SIGNAL_ARTIFACT_TYPE,
        "path": str(signal_path),
        "schema_version": SCHEMA_VERSION,
        "content_hash": content_hash,
    }
    manifest.setdefault("artifact_index", []).append(entry)
    return manifest
