from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from src.decision_intel.brokers.iol_adapter import ExecutionResponse, live_execute_order, paper_execute_order
from src.decision_intel.contracts.metadata_models import CURRENT_SCHEMA_VERSION
from src.decision_intel.execution.results_writer import load_execution_results, write_execution_results
from src.decision_intel.positions.positions_reconciler import apply_fills
from src.decision_intel.positions.positions_store import (
    PositionsSnapshot,
    load_positions_snapshot,
    save_positions_snapshot,
)
from src.decision_intel.utils.io import ensure_run_dir

def execute_plan(
    run_id: str,
    base_path: str = "runs",
    paper: bool = True,
    kill_switch_path: str | None = None,
    base_root: Path | None = None,
) -> Tuple[Path, Dict[str, Any], Path, Dict[str, Any], Path, Dict[str, Any]]:
    root = base_root or Path(__file__).resolve().parents[3]
    run_root = ensure_run_dir(run_id, base_path=base_path)
    plan_path = run_root / "artifacts" / f"execution.plan.v{CURRENT_SCHEMA_VERSION}.json"
    if not plan_path.exists():
        raise ValueError(f"execution.plan missing: {plan_path}")

    _check_kill_switch(kill_switch_path, root)
    if not paper:
        _ensure_paper_gate(root)

    plan_payload = json.loads(plan_path.read_text(encoding="utf-8"))
    orders = plan_payload.get("orders", [])
    if not isinstance(orders, list):
        orders = []
    current_order_ids = {
        str(order.get("order_id"))
        for order in orders
        if isinstance(order, dict) and order.get("order_id")
    }

    existing_results = load_execution_results(run_id, base_path=base_path)
    results_by_id = {
        row.get("order_id"): row
        for row in existing_results
        if isinstance(row, dict) and row.get("order_id") in current_order_ids
    }

    positions_before = _load_positions_source(paper, root)
    snapshot_before_path, snapshot_before_entry = save_positions_snapshot(
        run_id=run_id,
        snapshot=positions_before,
        base_path=base_path,
        base_root=root,
        filename="positions_snapshot_before.json",
        artifact_name="positions.snapshot.before",
        artifact_type="positions.snapshot.before",
        asof_date=plan_payload.get("asof_date"),
        execution_date=plan_payload.get("execution_date"),
        execution_hour=plan_payload.get("execution_hour"),
    )
    ordered = _sorted_orders(orders)
    new_results: List[Dict[str, Any]] = []

    for order in ordered:
        order_id = order.get("order_id")
        if not order_id:
            continue
        if order_id in results_by_id:
            continue
        response = _execute_order(order, paper)
        entry = _build_result_entry(order, response, paper)
        results_by_id[order_id] = entry
        new_results.append(entry)
        if response.status not in {"FILLED"}:
            raise RuntimeError(f"execution halted: order {order_id} {response.status}")

    results_list = sorted(results_by_id.values(), key=lambda row: str(row.get("order_id") or ""))
    results_path, results_entry = write_execution_results(
        run_id=run_id,
        results=results_list,
        base_path=base_path,
        asof_date=plan_payload.get("asof_date"),
        execution_date=plan_payload.get("execution_date"),
        execution_hour=plan_payload.get("execution_hour"),
    )

    results_to_apply = {row.get("order_id"): row for row in new_results if isinstance(row, dict)}
    positions_after, errors = apply_fills(positions_before, ordered, results_to_apply)
    if errors:
        raise RuntimeError(f"position reconciliation failed: {errors}")
    snapshot_path, snapshot_entry = save_positions_snapshot(
        run_id=run_id,
        snapshot=positions_after,
        base_path=base_path,
        base_root=root,
        filename="positions_snapshot_after.json",
        asof_date=plan_payload.get("asof_date"),
        execution_date=plan_payload.get("execution_date"),
        execution_hour=plan_payload.get("execution_hour"),
    )

    if paper:
        save_positions_snapshot(
            run_id=None,
            snapshot=positions_after,
            base_path=".",
            base_root=root,
            filename=str(Path("data") / "results" / "positions.json"),
            asof_date=plan_payload.get("asof_date"),
            execution_date=plan_payload.get("execution_date"),
            execution_hour=plan_payload.get("execution_hour"),
            include_metadata=False,
        )

    return results_path, results_entry, snapshot_before_path, snapshot_before_entry, snapshot_path, snapshot_entry


def _execute_order(order: Dict[str, Any], paper: bool) -> ExecutionResponse:
    if paper:
        return paper_execute_order(order)
    return live_execute_order(order)


def _sorted_orders(orders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    executable = [o for o in orders if o.get("order_status") in {"READY", "CLIPPED_CASH"}]
    def _key(order: Dict[str, Any]) -> Tuple[int, str]:
        side = order.get("order_side")
        side_rank = 0 if side == "SELL" else 1
        return (side_rank, str(order.get("order_id") or ""))

    return sorted(executable, key=_key)


def _build_result_entry(order: Dict[str, Any], response: ExecutionResponse, paper: bool) -> Dict[str, Any]:
    now = _utc_now_iso()
    return {
        "order_id": order.get("order_id"),
        "broker": order.get("broker_selected"),
        "status": response.status,
        "filled_qty": response.filled_qty,
        "avg_fill_price": response.avg_fill_price,
        "fees_actual": response.fees_actual,
        "timestamps": {"sent_at": now, "filled_at": now if response.status == "FILLED" else None},
        "error": response.error,
        "paper_mode": bool(paper),
    }


def _load_positions_source(paper: bool, base_root: Path) -> PositionsSnapshot:
    if paper:
        return load_positions_snapshot(base_root)
    broker_snapshot = base_root / "data" / "results" / "positions_broker_snapshot.json"
    if not broker_snapshot.exists():
        raise RuntimeError("live execution blocked: broker snapshot missing")
    payload = json.loads(broker_snapshot.read_text(encoding="utf-8"))
    temp_path = base_root / "data" / "results" / "positions.json"
    temp_path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    return load_positions_snapshot(base_root)


def _check_kill_switch(kill_switch_path: str | None, base_root: Path) -> None:
    if os.getenv("KILL_SWITCH") in {"1", "true", "TRUE"}:
        raise RuntimeError("kill switch enabled via env")
    path = Path(kill_switch_path) if kill_switch_path else (base_root / "data" / "controls" / "kill_switch.json")
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("enabled") is True:
                raise RuntimeError("kill switch enabled via file")
        except json.JSONDecodeError:
            raise RuntimeError("kill switch enabled via file")


def _ensure_paper_gate(base_root: Path) -> None:
    gate_path = base_root / "data" / "controls" / "paper_passed.flag"
    if not gate_path.exists():
        raise RuntimeError("live execution blocked: paper gate not satisfied")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
