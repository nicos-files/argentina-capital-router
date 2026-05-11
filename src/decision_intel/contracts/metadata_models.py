from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

CURRENT_SCHEMA_VERSION = "1.0.0"
MIN_READER_VERSION = "1.0.0"


class RunStatus(str, Enum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"
    SKIPPED = "SKIPPED"


@dataclass(frozen=True)
class ArtifactRef:
    name: str
    type: str
    path: str
    schema_version: str
    content_hash: Optional[str] = None


@dataclass(frozen=True)
class SkipRecord:
    code: str
    reason: str


@dataclass(frozen=True)
class ConfigRef:
    snapshot_path: str
    hash: Optional[str] = None


@dataclass(frozen=True)
class ManifestTimestamps:
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


@dataclass(frozen=True)
class RunManifest:
    schema_version: str
    reader_min_version: str
    run_id: str
    status: RunStatus
    timestamps: ManifestTimestamps
    config: ConfigRef
    data_snapshot_ids: Dict[str, str] = field(default_factory=dict)
    artifact_index: List[ArtifactRef] = field(default_factory=list)
    skips: List[SkipRecord] = field(default_factory=list)
    error: Optional[Dict[str, str]] = None
