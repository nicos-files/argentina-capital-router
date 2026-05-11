from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, List, Tuple

from src.decision_intel.positions.positions_store import PositionRecord, PositionsSnapshot


def apply_fills(
    snapshot: PositionsSnapshot,
    orders: List[Dict[str, Any]],
    results_by_id: Dict[str, Dict[str, Any]],
) -> Tuple[PositionsSnapshot, List[str]]:
    errors: List[str] = []
    positions = dict(snapshot.positions)
    cash_by_currency = dict(snapshot.cash_by_currency)
    cash_by_broker = {broker: dict(cash) for broker, cash in snapshot.cash_by_broker.items()}

    for order in orders:
        order_id = order.get("order_id")
        result = results_by_id.get(order_id) if order_id else None
        if not result or result.get("status") != "FILLED":
            continue
        side = order.get("order_side")
        if side not in {"BUY", "SELL"}:
            continue
        qty = float(result.get("filled_qty") or 0.0)
        if qty <= 0:
            continue
        broker = order.get("broker_selected") or "generic_us"
        asset_id = order.get("asset_id") or order.get("ticker")
        currency = order.get("currency") or "USD"
        fx_rate_used = order.get("fx_rate_used")
        price = result.get("avg_fill_price")
        fees_actual = float(result.get("fees_actual") or 0.0)
        if not isinstance(asset_id, str) or not asset_id:
            errors.append("missing_asset_id")
            continue
        if price is None:
            errors.append(f"missing_price:{asset_id}")
            continue

        if side == "SELL":
            position = positions.get(asset_id)
            if not position or position.qty < qty - 1e-9:
                errors.append(f"insufficient_qty:{asset_id}")
                continue
            new_qty = position.qty - qty
            if new_qty <= 0:
                positions.pop(asset_id, None)
            else:
                positions[asset_id] = replace(position, qty=new_qty)
            proceeds = qty * float(price)
            _adjust_cash(cash_by_currency, cash_by_broker, broker, currency, proceeds)
            _deduct_fees(cash_by_currency, cash_by_broker, broker, currency, fees_actual, fx_rate_used)
        else:
            cost = qty * float(price)
            cash_bucket = _cash_bucket(cash_by_currency, cash_by_broker, broker, currency)
            fee_ccy = _fees_in_order_currency(fees_actual, currency, fx_rate_used)
            total_cost = cost + fee_ccy
            if cash_bucket is not None and cash_bucket < total_cost - 1e-9:
                errors.append(f"insufficient_cash:{asset_id}")
                continue
            position = positions.get(asset_id)
            if position:
                new_qty = position.qty + qty
                if new_qty <= 0:
                    errors.append(f"invalid_qty:{asset_id}")
                    continue
                new_avg = ((position.avg_price * position.qty) + (float(price) * qty)) / new_qty
                positions[asset_id] = replace(position, qty=new_qty, avg_price=new_avg)
            else:
                positions[asset_id] = PositionRecord(
                    qty=qty,
                    avg_price=float(price),
                    broker=broker,
                    currency=currency,
                )
            _adjust_cash(cash_by_currency, cash_by_broker, broker, currency, -cost)
            _deduct_fees(cash_by_currency, cash_by_broker, broker, currency, fees_actual, fx_rate_used)

    return PositionsSnapshot(
        positions=positions,
        cash_by_currency=cash_by_currency,
        cash_by_broker=cash_by_broker,
    ), errors


def _adjust_cash(
    cash_by_currency: Dict[str, float],
    cash_by_broker: Dict[str, Dict[str, float]],
    broker: str,
    currency: str,
    delta_ccy: float,
) -> None:
    if broker in cash_by_broker:
        cash_by_broker.setdefault(broker, {})
        cash_by_broker[broker][currency] = cash_by_broker[broker].get(currency, 0.0) + delta_ccy
    if cash_by_currency is not None:
        cash_by_currency[currency] = cash_by_currency.get(currency, 0.0) + delta_ccy


def _cash_bucket(
    cash_by_currency: Dict[str, float],
    cash_by_broker: Dict[str, Dict[str, float]],
    broker: str,
    currency: str,
) -> float | None:
    if broker in cash_by_broker and currency in cash_by_broker[broker]:
        return cash_by_broker[broker][currency]
    if currency in cash_by_currency:
        return cash_by_currency[currency]
    return None


def _deduct_fees(
    cash_by_currency: Dict[str, float],
    cash_by_broker: Dict[str, Dict[str, float]],
    broker: str,
    currency: str,
    fees_actual_usd: float,
    fx_rate_used: Any,
) -> None:
    fee_ccy = _fees_in_order_currency(fees_actual_usd, currency, fx_rate_used)
    if fee_ccy <= 0:
        return
    _adjust_cash(cash_by_currency, cash_by_broker, broker, currency, -fee_ccy)


def _fees_in_order_currency(fees_actual_usd: float, currency: str, fx_rate_used: Any) -> float:
    if fees_actual_usd <= 0:
        return 0.0
    if currency == "USD":
        return float(fees_actual_usd)
    if isinstance(fx_rate_used, (int, float)) and float(fx_rate_used) > 0:
        return float(fees_actual_usd) / float(fx_rate_used)
    return float(fees_actual_usd)
