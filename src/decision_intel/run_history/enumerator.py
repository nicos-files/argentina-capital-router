from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.decision_intel.contracts.metadata_models import CURRENT_SCHEMA_VERSION


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    status: str
    created_at: str
    started_at: Optional[str]
    completed_at: Optional[str]
    strategy_id: Optional[str]
    horizon: Optional[str]


def enumerate_runs(base_path: str = "runs") -> List[RunSummary]:
    base = Path(base_path)
    if not base.exists():
        return []
    summaries: List[Tuple[datetime, RunSummary]] = []
    for run_dir in sorted(path for path in base.iterdir() if path.is_dir()):
        manifest_path = run_dir / "manifests" / f"run_manifest.v{CURRENT_SCHEMA_VERSION}.json"
        if not manifest_path.exists():
            continue
        summary = _load_summary(manifest_path)
        created_at_dt = _parse_timestamp(summary.created_at)
        summaries.append((created_at_dt, summary))
    summaries.sort(key=lambda item: (item[0], item[1].run_id), reverse=True)
    return [summary for _, summary in summaries]


def _load_summary(manifest_path: Path) -> RunSummary:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("manifest must be a JSON object")
    run_id = _require_field(data, "run_id")
    status = _require_field(data, "status")
    timestamps = _require_dict(data, "timestamps")
    created_at = _require_field(timestamps, "created_at")
    started_at = timestamps.get("started_at")
    completed_at = timestamps.get("completed_at")
    strategy_id = data.get("strategy_id")
    horizon = data.get("horizon")
    return RunSummary(
        run_id=run_id,
        status=status,
        created_at=created_at,
        started_at=started_at,
        completed_at=completed_at,
        strategy_id=strategy_id,
        horizon=horizon,
    )


def _require_field(data: Dict[str, Any], field: str) -> Any:
    if field not in data:
        raise ValueError(f"manifest missing required field: {field}")
    return data[field]


def _require_dict(data: Dict[str, Any], field: str) -> Dict[str, Any]:
    value = _require_field(data, field)
    if not isinstance(value, dict):
        raise ValueError(f"manifest field {field} must be an object")
    return value


def _parse_timestamp(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)
