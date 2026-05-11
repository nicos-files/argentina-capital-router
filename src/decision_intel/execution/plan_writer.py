from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from src.decision_intel.contracts.metadata_models import CURRENT_SCHEMA_VERSION, MIN_READER_VERSION
from src.decision_intel.utils.io import ensure_run_dir, validate_run_write_path


EXECUTABLE_STATUSES = {"READY", "CLIPPED_CASH"}


def write_execution_plan(
    run_id: str,
    recommendations_path: str | Path,
    base_path: str = "runs",
) -> Tuple[Path, Dict[str, Any]]:
    run_root = ensure_run_dir(run_id, base_path=base_path)
    payload = json.loads(Path(recommendations_path).read_text(encoding="utf-8"))
    orders = _build_orders(
        run_id=run_id,
        recommendations=payload.get("recommendations", []),
        asof_date=payload.get("asof_date"),
        execution_date=payload.get("execution_date"),
        execution_hour=payload.get("execution_hour"),
        policy_id=payload.get("policy_id"),
        policy_version=payload.get("policy_version"),
    )

    plan_payload = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "reader_min_version": MIN_READER_VERSION,
        "run_id": run_id,
        "asof_date": payload.get("asof_date"),
        "execution_date": payload.get("execution_date"),
        "execution_hour": payload.get("execution_hour"),
        "policy_id": payload.get("policy_id"),
        "policy_version": payload.get("policy_version"),
        "cash_policy": payload.get("cash_policy"),
        "cash_summary": payload.get("cash_summary", {}),
        "orders": orders,
    }

    serialized = json.dumps(plan_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    output_path = validate_run_write_path(
        run_id,
        run_root / "artifacts" / f"execution.plan.v{CURRENT_SCHEMA_VERSION}.json",
        base_path=base_path,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(serialized, encoding="utf-8")

    run_root_abs = run_root.resolve()
    entry = {
        "name": "execution.plan",
        "type": "execution.plan",
        "path": output_path.resolve().relative_to(run_root_abs).as_posix(),
        "schema_version": CURRENT_SCHEMA_VERSION,
        "content_hash": _hash_text(serialized),
    }
    return output_path, entry


def _build_orders(
    run_id: str,
    recommendations: List[Dict[str, Any]],
    asof_date: str | None,
    execution_date: str | None,
    execution_hour: str | None,
    policy_id: str | None,
    policy_version: str | None,
) -> List[Dict[str, Any]]:
    orders: List[Dict[str, Any]] = []
    for rec in recommendations:
        status = rec.get("order_status")
        if status not in EXECUTABLE_STATUSES:
            continue
        order_qty = float(rec.get("order_qty") or 0.0)
        order_side = rec.get("order_side")
        if order_qty <= 0 or order_side not in {"BUY", "SELL"}:
            continue
        order_id = _order_id(
            run_id,
            rec.get("horizon"),
            rec.get("asset_id"),
            order_side,
            rec.get("broker_selected"),
            order_qty,
        )
        orders.append(
            {
                "order_id": order_id,
                "run_id": run_id,
                "ticker": rec.get("ticker"),
                "asset_id": rec.get("asset_id"),
                "horizon": rec.get("horizon"),
                "broker_selected": rec.get("broker_selected"),
                "order_side": order_side,
                "order_type": rec.get("order_type"),
                "time_in_force": rec.get("time_in_force"),
                "order_qty": order_qty,
                "order_notional_usd": rec.get("order_notional_usd"),
                "order_notional_ccy": rec.get("order_notional_ccy"),
                "currency": rec.get("currency"),
                "fx_rate_used": rec.get("fx_rate_used"),
                "fx_rate_source": rec.get("fx_rate_source"),
                "price_used": rec.get("price_used"),
                "price_source": rec.get("price_source"),
                "min_notional_usd": rec.get("min_notional_usd"),
                "order_status": status,
                "fees_estimated_usd": rec.get("fees_estimated_usd"),
                "fees_one_way": rec.get("fees_one_way"),
                "fees_round_trip": rec.get("fees_round_trip"),
                "policy_id": policy_id,
                "policy_version": policy_version,
                "current_qty": rec.get("current_qty"),
                "qty_target": rec.get("qty_target"),
                "delta_qty": rec.get("delta_qty"),
                "asof_date": asof_date,
                "execution_date": execution_date,
                "execution_hour": execution_hour,
            }
        )
    return orders


def _order_id(
    run_id: str,
    horizon: str | None,
    asset_id: str | None,
    order_side: str | None,
    broker: str | None,
    order_qty: float,
) -> str:
    parts = [
        run_id,
        str(horizon or ""),
        str(asset_id or ""),
        str(order_side or ""),
        str(broker or ""),
        f"{order_qty:.6f}",
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
