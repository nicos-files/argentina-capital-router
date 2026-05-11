from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

from src.decision_intel.contracts.metadata_models import CURRENT_SCHEMA_VERSION


_EXPORT_FORMATS = {
    "decision.outputs": "parquet",
    "evaluation.metrics": "csv",
    "evaluation.normalized": "json",
    "evaluation.comparison": "json",
    "evaluation.analysis_summary": "json",
    "evaluation.policy": "json",
    "evaluation.policy_applied": "json",
    "evaluation.policy_applied_summary": "json",
    "recommendation.outputs": "csv",
    "execution.plan": "csv",
    "execution.results": "csv",
}


def export_artifacts(run_id: str, base_path: str = "runs") -> Path:
    run_root = Path(base_path) / run_id
    manifest_path = run_root / "manifests" / f"run_manifest.v{CURRENT_SCHEMA_VERSION}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifact_index: List[Dict[str, Any]] = manifest.get("artifact_index", [])

    export_root = run_root / "artifacts" / "exports"
    export_root.mkdir(parents=True, exist_ok=True)
    export_entries: List[Dict[str, Any]] = []

    for entry in artifact_index:
        name = entry.get("name")
        if name not in _EXPORT_FORMATS:
            continue
        fmt = _EXPORT_FORMATS[name]
        source_path = _resolve_manifest_path(run_root, entry.get("path"))
        actual_format, actual_path = _export_with_format(fmt, name, source_path, export_root)
        export_entries.append(
            {
                "name": f"export.{name}",
                "type": f"export.{actual_format}",
                "path": actual_path.relative_to(run_root).as_posix(),
                "schema_version": CURRENT_SCHEMA_VERSION,
                "content_hash": _hash_file(actual_path),
            }
        )

    for export_entry in export_entries:
        if not _has_artifact(artifact_index, export_entry):
            artifact_index.append(export_entry)

    manifest["artifact_index"] = artifact_index
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )
    return manifest_path


def _resolve_manifest_path(run_root: Path, value: str | None) -> Path:
    if not value:
        raise ValueError("artifact path missing in manifest")
    path = Path(value)
    if path.is_absolute():
        return path
    return run_root / path


def _export_with_format(format_name: str, artifact_name: str, source_path: Path, export_root: Path) -> tuple[str, Path]:
    if format_name == "parquet":
        return _export_parquet(artifact_name, source_path, export_root)
    if format_name == "csv":
        target_path = export_root / f"{artifact_name}.csv"
        if artifact_name == "recommendation.outputs":
            _export_recommendations_csv(source_path, target_path)
        elif artifact_name == "execution.plan":
            _export_execution_plan_csv(source_path, target_path)
        elif artifact_name == "execution.results":
            _export_execution_results_csv(source_path, target_path)
        else:
            _export_csv(source_path, target_path)
        return "csv", target_path
    target_path = export_root / f"{artifact_name}.json"
    _export_json(source_path, target_path)
    return "json", target_path


def _export_parquet(artifact_name: str, source_path: Path, export_root: Path) -> tuple[str, Path]:
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    rows = payload.get("decisions", [])
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        target_path = export_root / f"{artifact_name}.csv"
        _export_decisions_csv(rows, target_path)
        return "csv", target_path
    target_path = export_root / f"{artifact_name}.parquet"
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, target_path)
    return "parquet", target_path


def _export_csv(source_path: Path, target_path: Path) -> None:
    import csv

    payload = json.loads(source_path.read_text(encoding="utf-8"))
    metrics = payload.get("metrics", {})
    rows = [
        {
            "metric": key,
            "value": value,
            "run_id": payload.get("run_id"),
            "strategy_id": payload.get("strategy_id"),
            "variant_id": payload.get("variant_id"),
            "horizon": payload.get("horizon"),
        }
        for key in sorted(metrics.keys())
        for value in (metrics[key],)
    ]
    with target_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["metric", "value", "run_id", "strategy_id", "variant_id", "horizon"],
        )
        writer.writeheader()
        writer.writerows(rows)


def _export_decisions_csv(rows: List[Dict[str, Any]], target_path: Path) -> None:
    import csv

    fieldnames = sorted({key for row in rows for key in row.keys()})
    with target_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _export_recommendations_csv(source_path: Path, target_path: Path) -> None:
    import csv

    payload = json.loads(source_path.read_text(encoding="utf-8"))
    rows = payload.get("recommendations", [])
    formatted = []
    for row in rows:
        broker_costs = row.get("broker_costs", {})
        constraints = row.get("constraints", [])
        formatted.append(
            {
                "ticker": row.get("ticker"),
                "asset_id": row.get("asset_id"),
                "horizon": row.get("horizon"),
                "action": row.get("action"),
                "weight": row.get("weight"),
                "usd_target": row.get("usd_target"),
                "usd_target_effective": row.get("usd_target_effective"),
                "currency": row.get("currency"),
                "fx_rate_used": row.get("fx_rate_used"),
                "fx_rate_source": row.get("fx_rate_source"),
                "lot_size": row.get("lot_size"),
                "allow_fractional": row.get("allow_fractional"),
                "broker_selected": row.get("broker_selected"),
                "current_qty": row.get("current_qty"),
                "qty_target": row.get("qty_target"),
                "delta_qty": row.get("delta_qty"),
                "order_side": row.get("order_side"),
                "order_type": row.get("order_type"),
                "time_in_force": row.get("time_in_force"),
                "order_qty": row.get("order_qty"),
                "order_notional_usd": row.get("order_notional_usd"),
                "order_notional_ccy": row.get("order_notional_ccy"),
                "min_notional_usd": row.get("min_notional_usd"),
                "order_status": row.get("order_status"),
                "cash_available_usd": row.get("cash_available_usd"),
                "cash_used_usd": row.get("cash_used_usd"),
                "price_used": row.get("price_used"),
                "price_source": row.get("price_source"),
                "expected_return_gross_pct": row.get("expected_return_gross_pct"),
                "expected_return_net_pct": row.get("expected_return_net_pct"),
                "expected_return_net_usd": row.get("expected_return_net_usd"),
                "expected_return_source": row.get("expected_return_source"),
                "fees_estimated_usd": row.get("fees_estimated_usd"),
                "fees_one_way": row.get("fees_one_way"),
                "fees_round_trip": row.get("fees_round_trip"),
                "policy_id": row.get("policy_id"),
                "policy_version": row.get("policy_version"),
                "sizing_rule": row.get("sizing_rule"),
                "constraints": json.dumps(constraints, sort_keys=True, separators=(",", ":")),
                "reason": row.get("reason"),
                "broker_costs": json.dumps(broker_costs, sort_keys=True, separators=(",", ":")),
                "asof_date": row.get("asof_date"),
                "execution_date": row.get("execution_date"),
                "execution_hour": row.get("execution_hour"),
            }
        )
    with target_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "ticker",
                "asset_id",
                "horizon",
                "action",
                "weight",
                "usd_target",
                "usd_target_effective",
                "currency",
                "fx_rate_used",
                "fx_rate_source",
                "lot_size",
                "allow_fractional",
                "broker_selected",
                "current_qty",
                "qty_target",
                "delta_qty",
                "order_side",
                "order_type",
                "time_in_force",
                "order_qty",
                "order_notional_usd",
                "order_notional_ccy",
                "min_notional_usd",
                "order_status",
                "cash_available_usd",
                "cash_used_usd",
                "price_used",
                "price_source",
                "expected_return_gross_pct",
                "expected_return_net_pct",
                "expected_return_net_usd",
                "expected_return_source",
                "fees_estimated_usd",
                "fees_one_way",
                "fees_round_trip",
                "policy_id",
                "policy_version",
                "sizing_rule",
                "constraints",
                "reason",
                "broker_costs",
                "asof_date",
                "execution_date",
                "execution_hour",
            ],
        )
        writer.writeheader()
        writer.writerows(formatted)


def _export_execution_plan_csv(source_path: Path, target_path: Path) -> None:
    import csv

    payload = json.loads(source_path.read_text(encoding="utf-8"))
    rows = payload.get("orders", [])
    formatted = []
    for row in rows:
        formatted.append(
            {
                "order_id": row.get("order_id"),
                "run_id": row.get("run_id"),
                "asset_id": row.get("asset_id"),
                "ticker": row.get("ticker"),
                "horizon": row.get("horizon"),
                "broker_selected": row.get("broker_selected"),
                "order_side": row.get("order_side"),
                "order_type": row.get("order_type"),
                "time_in_force": row.get("time_in_force"),
                "order_qty": row.get("order_qty"),
                "order_notional_usd": row.get("order_notional_usd"),
                "order_notional_ccy": row.get("order_notional_ccy"),
                "currency": row.get("currency"),
                "fx_rate_used": row.get("fx_rate_used"),
                "fx_rate_source": row.get("fx_rate_source"),
                "price_used": row.get("price_used"),
                "price_source": row.get("price_source"),
                "min_notional_usd": row.get("min_notional_usd"),
                "order_status": row.get("order_status"),
                "fees_estimated_usd": row.get("fees_estimated_usd"),
                "fees_one_way": row.get("fees_one_way"),
                "fees_round_trip": row.get("fees_round_trip"),
                "policy_id": row.get("policy_id"),
                "policy_version": row.get("policy_version"),
                "current_qty": row.get("current_qty"),
                "qty_target": row.get("qty_target"),
                "delta_qty": row.get("delta_qty"),
                "asof_date": row.get("asof_date"),
                "execution_date": row.get("execution_date"),
                "execution_hour": row.get("execution_hour"),
            }
        )
    with target_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "order_id",
                "run_id",
                "asset_id",
                "ticker",
                "horizon",
                "broker_selected",
                "order_side",
                "order_type",
                "time_in_force",
                "order_qty",
                "order_notional_usd",
                "order_notional_ccy",
                "currency",
                "fx_rate_used",
                "fx_rate_source",
                "price_used",
                "price_source",
                "min_notional_usd",
                "order_status",
                "fees_estimated_usd",
                "fees_one_way",
                "fees_round_trip",
                "policy_id",
                "policy_version",
                "current_qty",
                "qty_target",
                "delta_qty",
                "asof_date",
                "execution_date",
                "execution_hour",
            ],
        )
        writer.writeheader()
        writer.writerows(formatted)


def _export_execution_results_csv(source_path: Path, target_path: Path) -> None:
    import csv

    payload = json.loads(source_path.read_text(encoding="utf-8"))
    rows = payload.get("results", [])
    formatted = []
    for row in rows:
        timestamps = row.get("timestamps", {}) if isinstance(row.get("timestamps"), dict) else {}
        formatted.append(
            {
                "order_id": row.get("order_id"),
                "broker": row.get("broker"),
                "status": row.get("status"),
                "filled_qty": row.get("filled_qty"),
                "avg_fill_price": row.get("avg_fill_price"),
                "fees_actual": row.get("fees_actual"),
                "sent_at": timestamps.get("sent_at"),
                "filled_at": timestamps.get("filled_at"),
                "error": row.get("error"),
                "paper_mode": row.get("paper_mode"),
            }
        )
    with target_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "order_id",
                "broker",
                "status",
                "filled_qty",
                "avg_fill_price",
                "fees_actual",
                "sent_at",
                "filled_at",
                "error",
                "paper_mode",
            ],
        )
        writer.writeheader()
        writer.writerows(formatted)


def _export_json(source_path: Path, target_path: Path) -> None:
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    target_path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _has_artifact(artifact_index: List[Dict[str, Any]], candidate: Dict[str, Any]) -> bool:
    for entry in artifact_index:
        if (
            entry.get("name") == candidate["name"]
            and entry.get("type") == candidate["type"]
            and entry.get("path") == candidate["path"]
        ):
            return True
    return False
