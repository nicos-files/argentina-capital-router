from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from src.decision_intel.utils.io import ensure_run_dir, validate_run_write_path


@dataclass(frozen=True)
class LogEvent:
    timestamp_utc: str
    level: str
    event_type: str
    run_id: str
    message: str
    context: Dict[str, Any]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    path.write_text(path.read_text(encoding="utf-8") + line + "\n" if path.exists() else line + "\n", encoding="utf-8")


def _validate_event(event: LogEvent) -> None:
    if not event.timestamp_utc:
        raise ValueError("timestamp_utc is required")
    if not event.level:
        raise ValueError("level is required")
    if not event.event_type:
        raise ValueError("event_type is required")
    if not event.run_id:
        raise ValueError("run_id is required")
    if not event.message:
        raise ValueError("message is required")
    if event.context is None:
        raise ValueError("context is required")


def write_run_event(
    run_id: str,
    level: str,
    event_type: str,
    message: str,
    context: Dict[str, Any],
    base_path: str = "runs",
) -> Path:
    ensure_run_dir(run_id, base_path=base_path)
    event = LogEvent(
        timestamp_utc=_utc_now_iso(),
        level=level,
        event_type=event_type,
        run_id=run_id,
        message=message,
        context=context,
    )
    _validate_event(event)
    log_path = validate_run_write_path(run_id, Path(base_path) / run_id / "logs" / "run.jsonl", base_path=base_path)
    _append_jsonl(log_path, event.__dict__)
    return log_path


def write_audit_event(
    run_id: str,
    level: str,
    event_type: str,
    message: str,
    context: Dict[str, Any],
    base_path: str = "runs",
) -> Path:
    ensure_run_dir(run_id, base_path=base_path)
    event = LogEvent(
        timestamp_utc=_utc_now_iso(),
        level=level,
        event_type=event_type,
        run_id=run_id,
        message=message,
        context=context,
    )
    _validate_event(event)
    log_path = validate_run_write_path(run_id, Path(base_path) / run_id / "logs" / "audit.jsonl", base_path=base_path)
    _append_jsonl(log_path, event.__dict__)
    return log_path
