from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from src.decision_intel.contracts.metadata_models import CURRENT_SCHEMA_VERSION, MIN_READER_VERSION
from src.decision_intel.utils.io import ensure_run_dir, validate_run_write_path


def write_execution_results(
    run_id: str,
    results: List[Dict[str, Any]],
    base_path: str = "runs",
    asof_date: str | None = None,
    execution_date: str | None = None,
    execution_hour: str | None = None,
) -> Tuple[Path, Dict[str, Any]]:
    run_root = ensure_run_dir(run_id, base_path=base_path)
    payload = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "reader_min_version": MIN_READER_VERSION,
        "run_id": run_id,
        "asof_date": asof_date,
        "execution_date": execution_date,
        "execution_hour": execution_hour,
        "generated_at": _utc_now_iso(),
        "results": results,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    output_path = validate_run_write_path(
        run_id,
        run_root / "artifacts" / f"execution.results.v{CURRENT_SCHEMA_VERSION}.json",
        base_path=base_path,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(serialized, encoding="utf-8")

    run_root_abs = run_root.resolve()
    entry = {
        "name": "execution.results",
        "type": "execution.results",
        "path": output_path.resolve().relative_to(run_root_abs).as_posix(),
        "schema_version": CURRENT_SCHEMA_VERSION,
        "content_hash": _hash_text(serialized),
    }
    return output_path, entry


def load_execution_results(
    run_id: str,
    base_path: str = "runs",
) -> List[Dict[str, Any]]:
    run_root = Path(base_path) / run_id
    path = run_root / "artifacts" / f"execution.results.v{CURRENT_SCHEMA_VERSION}.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    results = payload.get("results")
    return results if isinstance(results, list) else []


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
