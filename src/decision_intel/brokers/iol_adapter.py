from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class ExecutionResponse:
    status: str
    filled_qty: float
    avg_fill_price: float | None
    fees_actual: float
    error: Optional[str] = None


def paper_execute_order(order: Dict[str, Any]) -> ExecutionResponse:
    qty = float(order.get("order_qty") or 0.0)
    price = order.get("price_used")
    if qty <= 0:
        return ExecutionResponse(status="REJECTED", filled_qty=0.0, avg_fill_price=None, fees_actual=0.0, error="invalid_qty")
    if price is None:
        return ExecutionResponse(status="REJECTED", filled_qty=0.0, avg_fill_price=None, fees_actual=0.0, error="missing_price")
    fees = float(order.get("fees_estimated_usd") or 0.0)
    return ExecutionResponse(status="FILLED", filled_qty=qty, avg_fill_price=float(price), fees_actual=fees)


def live_execute_order(order: Dict[str, Any]) -> ExecutionResponse:
    _ = order
    return ExecutionResponse(
        status="FAILED",
        filled_qty=0.0,
        avg_fill_price=None,
        fees_actual=0.0,
        error="live_execution_not_implemented",
    )
