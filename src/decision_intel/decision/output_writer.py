from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from src.decision_intel.contracts.decisions.decision_constants import (
    DECISION_ARTIFACT_NAME,
    DECISION_ARTIFACT_TYPE,
    HORIZON_ENUM,
    READER_MIN_VERSION,
    SCHEMA_VERSION,
)
from src.decision_intel.utils.io import ensure_run_dir, validate_run_write_path


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_decision_outputs(
    run_id: str,
    decisions: List[Dict[str, Any]],
    strategy_id: str,
    variant_id: str | None,
    horizon: str,
    rule_refs: Dict[str, Any],
    config_snapshot_path: str,
    asof_date: str | None = None,
    base_path: str = "runs",
    content_hash: str | None = None,
) -> Tuple[Path, Dict[str, Any]]:
    if horizon not in HORIZON_ENUM:
        raise ValueError("horizon must be one of SHORT, MEDIUM, LONG")
    if not isinstance(rule_refs, dict) or "sizing_rule" not in rule_refs:
        raise ValueError("rule_refs must include sizing_rule, constraints, filters")
    if not isinstance(rule_refs.get("constraints"), list) or not all(
        isinstance(item, str) for item in rule_refs.get("constraints")
    ):
        raise ValueError("rule_refs.constraints must be a list of strings")
    if not isinstance(rule_refs.get("filters"), list) or not all(
        isinstance(item, str) for item in rule_refs.get("filters")
    ):
        raise ValueError("rule_refs.filters must be a list of strings")
    ensure_run_dir(run_id, base_path=base_path)
    normalized_decisions: List[Dict[str, Any]] = []
    for decision in decisions:
        item = dict(decision)
        if asof_date:
            outputs = item.get("outputs")
            outputs = dict(outputs) if isinstance(outputs, dict) else {}
            outputs.setdefault("asof_date", asof_date)
            item["outputs"] = outputs
        normalized_decisions.append(item)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "reader_min_version": READER_MIN_VERSION,
        "run_id": run_id,
        "strategy_id": strategy_id,
        "variant_id": variant_id,
        "horizon": horizon,
        "rule_refs": rule_refs,
        "config_snapshot_path": config_snapshot_path,
        "decisions": normalized_decisions,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if content_hash is None:
        content_hash = _hash_text(serialized)

    output_path = validate_run_write_path(
        run_id,
        Path(base_path) / run_id / "artifacts" / f"decision.outputs.v{SCHEMA_VERSION}.json",
        base_path=base_path,
    )
    output_path.write_text(serialized, encoding="utf-8")

    manifest_update = {
        "name": DECISION_ARTIFACT_NAME,
        "type": DECISION_ARTIFACT_TYPE,
        "path": output_path.as_posix(),
        "schema_version": SCHEMA_VERSION,
        "content_hash": content_hash,
    }
    return output_path, manifest_update
