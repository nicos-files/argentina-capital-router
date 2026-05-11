from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from src.decision_intel.assets.asset_metadata import get_asset_metadata
from src.decision_intel.brokers.broker_selector import (
    BROKER_FRACTIONAL,
    DEFAULT_BROKER,
    broker_min_notional_usd,
    build_fee_table,
    select_broker,
)
from src.decision_intel.positions.positions_store import PositionRecord
from src.risk import DEFAULT_RISK_CONFIG, RiskCheckInput, RiskCheckResult, RiskEngine


POLICY_ID = "policy.topk.net_after_fees.v1"
POLICY_VERSION = "1"

CAPITAL_USD = {"INTRADAY": 100.0, "LONG_TERM": 500.0}
TOP_K = {"INTRADAY": 5, "LONG_TERM": 8}
MAX_WEIGHT = {"INTRADAY": 0.25, "LONG_TERM": 0.20}
MIN_NET = {"INTRADAY": 0.008, "LONG_TERM": 0.05}
MIN_ORDER_USD = {"INTRADAY": 50.0, "LONG_TERM": 50.0}
MAX_POSITIONS = {"INTRADAY": 5, "LONG_TERM": 8}
MAX_TURNOVER = {"LONG_TERM": 1.00}
ORDER_TYPE_DEFAULT = "MARKET"
TIME_IN_FORCE_DEFAULT = "DAY"
CASH_POLICY = "clip_to_available"
ENABLE_INTRADAY_TO_LONG_TERM_FALLBACK = False
POLICY_RISK_CONFIG = dict(DEFAULT_RISK_CONFIG)


@dataclass(frozen=True)
class _Candidate:
    asset_id: str
    score: float
    base_weight: float
    model_score: float | None
    expected_return_gross_pct: float | None
    expected_return_source: str | None
    reason: str | None


@dataclass
class _CashPools:
    by_broker: Dict[str, Dict[str, float]]
    by_currency: Dict[str, float]
    fallback_usd: float
    source: str


def apply_topk_net_after_fees(
    decisions: List[Dict[str, Any]],
    asof_date: str | None,
    execution_date: str | None,
    execution_hour: str | None,
    price_map: Dict[str, float],
    positions: Dict[str, PositionRecord],
    cash_by_currency: Dict[str, float] | None = None,
    cash_by_broker: Dict[str, Dict[str, float]] | None = None,
) -> List[Dict[str, Any]]:
    risk_engine = _build_risk_engine()
    decisions_aug = list(decisions)
    has_long_term = _has_decision_type(decisions, "long_term")
    if ENABLE_INTRADAY_TO_LONG_TERM_FALLBACK and not has_long_term:
        decisions_aug.extend(_fallback_long_term(decisions))
    shared_cash_pools = None
    if cash_by_currency or cash_by_broker:
        shared_cash_pools = _build_cash_pools(cash_by_currency, cash_by_broker, 0.0)
    recommendations: List[Dict[str, Any]] = []
    recommendations.extend(
        _build_for_horizon(
            decisions_aug,
            "INTRADAY",
            "intraday",
            asof_date,
            execution_date,
            execution_hour,
            price_map,
            positions,
            cash_by_currency,
            cash_by_broker,
            shared_cash_pools,
            risk_engine,
        )
    )
    recommendations.extend(
        _build_for_horizon(
            decisions_aug,
            "LONG_TERM",
            "long_term",
            asof_date,
            execution_date,
            execution_hour,
            price_map,
            positions,
            cash_by_currency,
            cash_by_broker,
            shared_cash_pools,
            risk_engine,
        )
    )
    return recommendations


def _build_for_horizon(
    decisions: List[Dict[str, Any]],
    horizon: str,
    decision_type: str,
    asof_date: str | None,
    execution_date: str | None,
    execution_hour: str | None,
    price_map: Dict[str, float],
    positions: Dict[str, PositionRecord],
    cash_by_currency: Dict[str, float] | None,
    cash_by_broker: Dict[str, Dict[str, float]] | None,
    cash_pools: _CashPools | None = None,
    risk_engine: RiskEngine | None = None,
) -> List[Dict[str, Any]]:
    candidates = _collect_candidates(decisions, decision_type)
    if not candidates and not positions:
        return []

    candidates.sort(key=lambda row: (-row.score, row.asset_id))
    selected = candidates[: TOP_K[horizon]]

    items: Dict[str, Dict[str, Any]] = {}
    capital = CAPITAL_USD[horizon]
    base_weights = {item.asset_id: item.base_weight for item in selected}
    weights = _normalize_weights(base_weights)
    weights = _apply_caps(weights, MAX_WEIGHT[horizon])
    weights = _normalize_weights(weights)
    weights = _apply_min_order(selected, weights, capital, MIN_ORDER_USD[horizon])
    threshold = MIN_NET[horizon]

    for candidate in selected:
        weight = weights.get(candidate.asset_id, 0.0)
        item = _build_candidate_entry(
            candidate,
            horizon,
            weight,
            capital,
            threshold,
            asof_date,
            execution_date,
            execution_hour,
            price_map,
            positions,
        )
        items[candidate.asset_id] = item

    for asset_id, position in positions.items():
        if asset_id in items:
            continue
        item = _build_position_entry(
            asset_id,
            position,
            horizon,
            threshold,
            asof_date,
            execution_date,
            execution_hour,
            price_map,
        )
        items[asset_id] = item

    items = _renormalize_buys(
        items,
        horizon,
        MAX_WEIGHT[horizon],
        capital,
        threshold,
        price_map,
        positions,
        cash_by_currency,
        cash_by_broker,
        cash_pools,
        risk_engine,
    )
    return list(items.values())


def _collect_candidates(decisions: List[Dict[str, Any]], decision_type: str) -> List[_Candidate]:
    candidates: List[_Candidate] = []
    for decision in decisions:
        outputs = decision.get("outputs") if isinstance(decision.get("outputs"), dict) else {}
        if outputs.get("decision_type") != decision_type:
            continue
        asset_id = _clean_asset_id(decision.get("asset_id"))
        if not asset_id:
            continue
        model_score = outputs.get("model_score")
        score = _select_score(decision.get("signal"), outputs)
        base_weight = _select_base_weight(outputs, score)
        expected_return_gross_pct, expected_return_source = _extract_expected_return(outputs)
        reason = outputs.get("justificacion") if isinstance(outputs.get("justificacion"), str) else None
        candidates.append(
            _Candidate(
                asset_id=asset_id,
                score=score,
                base_weight=base_weight,
                model_score=float(model_score) if _is_number(model_score) else None,
                expected_return_gross_pct=expected_return_gross_pct,
                expected_return_source=expected_return_source,
                reason=reason,
            )
        )
    return candidates


def _has_decision_type(decisions: List[Dict[str, Any]], decision_type: str) -> bool:
    for decision in decisions:
        outputs = decision.get("outputs") if isinstance(decision.get("outputs"), dict) else {}
        if outputs.get("decision_type") == decision_type:
            return True
    return False


def _fallback_long_term(decisions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    fallback: List[Dict[str, Any]] = []
    for decision in decisions:
        outputs = decision.get("outputs") if isinstance(decision.get("outputs"), dict) else {}
        if outputs.get("decision_type") != "intraday":
            continue
        new_decision = dict(decision)
        new_outputs = dict(outputs)
        new_outputs["decision_type"] = "long_term"
        reason = new_outputs.get("justificacion")
        flag = "fallback_long_term_from_intraday=true"
        if isinstance(reason, str) and reason:
            new_outputs["justificacion"] = f"{reason} | {flag}"
        else:
            new_outputs["justificacion"] = flag
        new_decision["outputs"] = new_outputs
        fallback.append(new_decision)
    return fallback


def _select_score(signal: Any, outputs: Dict[str, Any]) -> float:
    model_score = outputs.get("model_score")
    if _is_number(model_score):
        return float(model_score)
    if _is_number(signal):
        return float(signal)
    return 1.0


def _select_base_weight(outputs: Dict[str, Any], score: float) -> float:
    peso = outputs.get("peso_pct")
    if _is_number(peso):
        return float(peso)
    return float(score)


def _extract_expected_return(outputs: Dict[str, Any]) -> Tuple[float | None, str | None]:
    value = outputs.get("expected_return_gross_pct")
    if _is_number(value):
        return float(value), "calibrated"
    value = outputs.get("target_regresion_t+1")
    if _is_number(value):
        return float(value), "model_regression"
    return None, None


def _apply_min_order(
    candidates: List[_Candidate],
    weights: Dict[str, float],
    capital: float,
    min_order: float,
) -> Dict[str, float]:
    if not candidates or capital <= 0 or min_order <= 0:
        return weights
    min_weight = min_order / capital
    if min_weight <= 0:
        return weights
    selected = [c for c in candidates if weights.get(c.asset_id, 0.0) > 0]
    if not selected:
        return weights
    selected.sort(key=lambda c: (-c.score, c.asset_id))
    while selected and len(selected) * min_weight > 1.0:
        selected.pop()
    if not selected:
        return {c.asset_id: 0.0 for c in candidates}
    base_total = sum(max(weights.get(c.asset_id, 0.0), 0.0) for c in selected)
    remaining = 1.0 - (len(selected) * min_weight)
    adjusted: Dict[str, float] = {}
    for candidate in selected:
        adjusted[candidate.asset_id] = min_weight
    if remaining > 0:
        if base_total <= 0:
            extra = remaining / len(selected)
            for candidate in selected:
                adjusted[candidate.asset_id] += extra
        else:
            for candidate in selected:
                adjusted[candidate.asset_id] += (
                    remaining * max(weights.get(candidate.asset_id, 0.0), 0.0) / base_total
                )
    for candidate in candidates:
        adjusted.setdefault(candidate.asset_id, 0.0)
    return adjusted


def _build_candidate_entry(
    candidate: _Candidate,
    horizon: str,
    weight: float,
    capital: float,
    threshold: float,
    asof_date: str | None,
    execution_date: str | None,
    execution_hour: str | None,
    price_map: Dict[str, float],
    positions: Dict[str, PositionRecord],
) -> Dict[str, Any]:
    asset_id = candidate.asset_id
    position = positions.get(asset_id)
    current_qty = position.qty if position else 0.0
    meta = get_asset_metadata(asset_id, price_source="features.close")
    currency = position.currency if position else meta.currency
    price_used = price_map.get(asset_id)
    fx_rate_used, fx_rate_source = _resolve_fx_rate(meta, position)
    price_usd = _price_in_usd(price_used, fx_rate_used)

    usd_target = weight * capital
    broker_selected, broker_costs, fees_one_way, fees_round_trip = _select_broker_for_order(
        usd_target,
        currency,
        "equity",
    )
    allow_fractional = meta.allow_fractional and BROKER_FRACTIONAL.get(broker_selected, True)
    qty_target, usd_effective = _compute_qty_and_usd(usd_target, price_usd, allow_fractional, meta.lot_size)
    expected_gross_pct, expected_source, missing_score = _expected_return_gross_pct(candidate, horizon)

    gross_usd = expected_gross_pct * usd_effective
    net_usd = gross_usd - fees_round_trip
    net_buy_pct = net_usd / usd_effective if usd_effective > 0 else 0.0
    eligible_buy = weight > 0 and price_usd is not None and usd_effective > 0 and net_buy_pct >= threshold
    min_capital_viable_usd = _estimate_min_viable_notional_usd(expected_gross_pct, threshold, broker_selected)

    target_qty = qty_target if eligible_buy else 0.0
    action = _resolve_action(current_qty, target_qty, price_used)

    if action in {"SELL", "EXIT"} and position and price_used is not None:
        sell_qty = max(current_qty - target_qty, 0.0)
        sell_value = sell_qty * (price_usd or 0.0)
        broker_selected, broker_costs, fees_one_way, fees_round_trip = _select_broker_for_order(
            sell_value,
            currency,
            "equity",
            broker_override=position.broker,
        )
        sell_gross_pct, sell_net_pct, sell_net_usd = _sell_returns_for_qty(
            position, price_used, sell_qty, fees_one_way, fx_rate_used
        )
        expected_gross_pct = sell_gross_pct
        expected_source = "position_pnl"
        net_buy_pct = sell_net_pct
        net_usd = sell_net_usd
        usd_effective = sell_value
    elif action == "HOLD" and position and price_used is not None:
        usd_effective = current_qty * (price_usd or 0.0)
        net_usd = expected_gross_pct * usd_effective
        net_buy_pct = expected_gross_pct
        fees_one_way = 0.0
        fees_round_trip = 0.0

    item = _base_item(
        asset_id=asset_id,
        horizon=horizon,
        action=action,
        weight=weight,
        usd_target=usd_target,
        usd_target_effective=usd_effective,
        qty_target=target_qty,
        price_used=price_used,
        price_source=meta.price_source,
        currency=currency,
        fx_rate_used=fx_rate_used,
        fx_rate_source=fx_rate_source,
        lot_size=meta.lot_size,
        allow_fractional=allow_fractional,
        expected_return_gross_pct=expected_gross_pct,
        expected_return_net_pct=net_buy_pct,
        expected_return_net_usd=net_usd,
        expected_return_source=expected_source,
        fees_estimated_usd=fees_round_trip if action == "BUY" else fees_one_way,
        fees_one_way=fees_one_way,
        fees_round_trip=fees_round_trip,
        broker_costs=broker_costs,
        reason=_build_reason(
            candidate.reason,
            expected_gross_pct,
            net_buy_pct,
            threshold,
            missing_score,
            action,
            min_capital_viable_usd,
        ),
        asof_date=asof_date,
        execution_date=execution_date,
        execution_hour=execution_hour,
        broker_selected=broker_selected,
        current_qty=current_qty,
        delta_qty=target_qty - current_qty,
        min_capital_viable_usd=min_capital_viable_usd,
    )
    item["_base_reason"] = candidate.reason
    item["_missing_score"] = missing_score

    if action == "EXIT":
        _zero_trade_fields(item)
    if currency != "USD" and fx_rate_used is None:
        _append_constraint(item, "fx_rate_missing")
        item["order_status"] = "BLOCKED_FX"

    return item


def _build_position_entry(
    asset_id: str,
    position: PositionRecord,
    horizon: str,
    threshold: float,
    asof_date: str | None,
    execution_date: str | None,
    execution_hour: str | None,
    price_map: Dict[str, float],
) -> Dict[str, Any]:
    meta = get_asset_metadata(asset_id, price_source="features.close")
    currency = position.currency or meta.currency
    price_used = price_map.get(asset_id)
    fx_rate_used, fx_rate_source = _resolve_fx_rate(meta, position)
    price_usd = _price_in_usd(price_used, fx_rate_used)
    target_qty = 0.0
    action = _resolve_action(position.qty, target_qty, price_used)
    sell_value = position.qty * (price_usd or 0.0)
    broker_selected, broker_costs, fees_one_way, fees_round_trip = _select_broker_for_order(
        sell_value,
        currency,
        "equity",
        broker_override=position.broker,
    )
    sell_gross_pct, sell_net_pct, sell_net_usd = _sell_returns(position, price_used, fees_one_way, fx_rate_used)
    reason = _build_reason(
        None,
        sell_gross_pct,
        sell_net_pct,
        threshold,
        False,
        action,
        None,
    )
    item = _base_item(
        asset_id=asset_id,
        horizon=horizon,
        action=action,
        weight=0.0,
        usd_target=0.0,
        usd_target_effective=sell_value,
        qty_target=target_qty,
        price_used=price_used,
        price_source=meta.price_source,
        currency=currency,
        fx_rate_used=fx_rate_used,
        fx_rate_source=fx_rate_source,
        lot_size=meta.lot_size,
        allow_fractional=meta.allow_fractional,
        expected_return_gross_pct=sell_gross_pct,
        expected_return_net_pct=sell_net_pct,
        expected_return_net_usd=sell_net_usd,
        expected_return_source="position_pnl",
        fees_estimated_usd=fees_one_way,
        fees_one_way=fees_one_way,
        fees_round_trip=fees_round_trip,
        broker_costs=broker_costs,
        reason=reason,
        asof_date=asof_date,
        execution_date=execution_date,
        execution_hour=execution_hour,
        broker_selected=broker_selected,
        current_qty=position.qty,
        delta_qty=target_qty - position.qty,
    )
    if action == "EXIT":
        _zero_trade_fields(item)
    if currency != "USD" and fx_rate_used is None:
        _append_constraint(item, "fx_rate_missing")
        item["order_status"] = "BLOCKED_FX"
    return item


def _renormalize_buys(
    items: Dict[str, Dict[str, Any]],
    horizon: str,
    cap: float,
    capital: float,
    threshold: float,
    price_map: Dict[str, float],
    positions: Dict[str, PositionRecord],
    cash_by_currency: Dict[str, float] | None,
    cash_by_broker: Dict[str, Dict[str, float]] | None,
    cash_pools: _CashPools | None = None,
    risk_engine: RiskEngine | None = None,
) -> Dict[str, Dict[str, Any]]:
    buy_weights = {key: item["weight"] for key, item in items.items() if item["action"] == "BUY"}
    buy_weights = _normalize_weights(buy_weights)
    buy_weights = _apply_caps_retain(buy_weights, cap)
    _apply_buy_weights(
        items,
        buy_weights,
        capital,
        threshold,
        price_map,
        positions,
            cash_by_currency,
            cash_by_broker,
            horizon,
            cash_pools,
            risk_engine,
        )

    failed = [key for key, item in items.items() if item["action"] == "BUY" and item["expected_return_net_pct"] < threshold]
    if failed:
        for key in failed:
            _demote_buy(items, key, positions, price_map, threshold)
        buy_weights = {key: item["weight"] for key, item in items.items() if item["action"] == "BUY"}
        buy_weights = _normalize_weights(buy_weights)
        buy_weights = _apply_caps_retain(buy_weights, cap)
        _apply_buy_weights(
            items,
            buy_weights,
            capital,
            threshold,
            price_map,
            positions,
            cash_by_currency,
            cash_by_broker,
            horizon,
            cash_pools,
            risk_engine,
        )

    _apply_guardrails(items, horizon, capital, cap, threshold, price_map, positions, cash_by_currency, cash_by_broker)

    for item in items.values():
        if item["action"] != "BUY":
            item["weight"] = 0.0
            item["usd_target"] = 0.0
        _refresh_order_fields(item, price_map, positions, horizon, capital)
        item.pop("_base_reason", None)
        item.pop("_missing_score", None)
    return items


def _apply_buy_weights(
    items: Dict[str, Dict[str, Any]],
    buy_weights: Dict[str, float],
    capital: float,
    threshold: float,
    price_map: Dict[str, float],
    positions: Dict[str, PositionRecord],
    cash_by_currency: Dict[str, float] | None,
    cash_by_broker: Dict[str, Dict[str, float]] | None,
    horizon: str,
    cash_pools: _CashPools | None = None,
    risk_engine: RiskEngine | None = None,
) -> None:
    pools = cash_pools or _build_cash_pools(cash_by_currency, cash_by_broker, capital)
    active_risk_engine = risk_engine or _build_risk_engine()
    buy_keys = [key for key, item in items.items() if item.get("action") == "BUY"]
    buy_keys.sort(
        key=lambda key: (
            -float(items[key].get("expected_return_net_pct") or 0.0),
            key,
        )
    )

    for key in buy_keys:
        item = items[key]
        weight = buy_weights.get(key, 0.0)
        item["weight"] = weight

        meta = get_asset_metadata(key, price_source="features.close")
        position = positions.get(key)
        currency = position.currency if position else meta.currency
        price_used = price_map.get(key)
        fx_rate_used, fx_rate_source = _resolve_fx_rate(meta, position)
        price_usd = _price_in_usd(price_used, fx_rate_used)
        current_qty = position.qty if position else 0.0
        gross_pct = float(item.get("expected_return_gross_pct") or 0.0)

        item["price_used"] = price_used
        item["price_source"] = meta.price_source
        item["currency"] = currency
        item["fx_rate_used"] = fx_rate_used
        item["fx_rate_source"] = fx_rate_source
        item["lot_size"] = meta.lot_size
        item["allow_fractional"] = meta.allow_fractional
        item["current_qty"] = current_qty
        item["cash_available_usd"] = None
        item["cash_used_usd"] = 0.0

        usd_target = weight * capital
        item["usd_target"] = usd_target

        if weight <= 0 or usd_target <= 0:
            _zero_trade_fields(item)
            item["action"] = _resolve_action(current_qty, 0.0, price_used)
            item["order_status"] = "NO_ORDER"
            continue

        if price_usd is None:
            _zero_trade_fields(item)
            item["action"] = _resolve_action(current_qty, 0.0, price_used)
            item["order_side"] = "BUY"
            if currency != "USD" and fx_rate_used is None:
                item["order_status"] = "BLOCKED_FX"
                _append_constraint(item, "fx_rate_missing")
            else:
                item["order_status"] = "BLOCKED_PRICE"
                _append_constraint(item, "price_missing")
            continue

        best_choice: Dict[str, Any] | None = None
        best_fee: float | None = None
        min_notional_floor = None
        max_cash_seen = 0.0
        for broker_name in sorted(BROKER_FRACTIONAL.keys()):
            allow_fractional = meta.allow_fractional and BROKER_FRACTIONAL.get(broker_name, True)
            available_cash_usd, cash_bucket = _available_cash_usd(
                pools, broker_name, currency, fx_rate_used
            )
            if available_cash_usd is None:
                continue
            max_cash_seen = max(max_cash_seen, available_cash_usd)
            spend_limit = min(usd_target, available_cash_usd)
            qty_target = 0.0
            usd_effective = 0.0
            fee_one_way = 0.0
            for _ in range(3):
                qty_target, usd_effective = _compute_qty_and_usd(
                    spend_limit, price_usd, allow_fractional, meta.lot_size
                )
                if usd_effective <= 0:
                    break
                fee_one_way = _fee_one_way_for_broker(broker_name, usd_effective)
                affordable_limit = max(available_cash_usd - fee_one_way, 0.0)
                next_spend_limit = min(usd_target, affordable_limit)
                if abs(next_spend_limit - spend_limit) <= 1e-9:
                    break
                spend_limit = next_spend_limit
            if usd_effective <= 0 or usd_effective + fee_one_way > available_cash_usd + 1e-9:
                continue
            min_notional = _effective_min_notional_usd(broker_name, horizon)
            min_notional_floor = min_notional if min_notional_floor is None else min(min_notional_floor, min_notional)
            if usd_effective < min_notional:
                continue
            if best_fee is None or fee_one_way < best_fee or (
                fee_one_way == best_fee and broker_name < best_choice["broker"]
            ):
                best_fee = fee_one_way
                best_choice = {
                    "broker": broker_name,
                    "allow_fractional": allow_fractional,
                    "qty_target": qty_target,
                    "usd_effective": usd_effective,
                    "cash_bucket": cash_bucket,
                    "available_cash_usd": available_cash_usd,
                    "min_notional": min_notional,
                    "clipped_cash": (usd_effective + fee_one_way) < available_cash_usd - 1e-9 or usd_effective < usd_target - 1e-9,
                    "spend_limit": spend_limit,
                    "cash_consumed_usd": usd_effective + fee_one_way,
                }

        if best_choice is None:
            _zero_trade_fields(item)
            item["action"] = _resolve_action(current_qty, 0.0, price_used)
            item["order_side"] = "BUY"
            if max_cash_seen <= 0:
                item["order_status"] = "BLOCKED_CASH"
                _append_constraint(item, "cash_insufficient")
            elif min_notional_floor is not None and usd_target < min_notional_floor:
                item["order_status"] = "BLOCKED_MIN_NOTIONAL"
                _append_constraint(item, "min_notional")
            else:
                item["order_status"] = "BLOCKED_CASH"
                _append_constraint(item, "cash_insufficient")
            continue

        broker_selected = best_choice["broker"]
        qty_target = best_choice["qty_target"]
        usd_effective = best_choice["usd_effective"]
        allow_fractional = best_choice["allow_fractional"]
        min_notional = best_choice["min_notional"]
        cash_bucket = best_choice["cash_bucket"]
        cash_consumed_usd = best_choice["cash_consumed_usd"]

        broker_selected, broker_costs, fees_one_way, fees_round_trip = _select_broker_for_order(
            usd_effective,
            currency,
            "equity",
            broker_override=broker_selected,
        )

        net_pct = _net_pct(gross_pct, fees_round_trip, usd_effective)
        net_usd = _net_usd(gross_pct, fees_round_trip, usd_effective)
        delta_qty = qty_target - current_qty
        risk_result = active_risk_engine.evaluate(
            RiskCheckInput(
                symbol=key,
                side="BUY",
                quantity=qty_target,
                notional=usd_effective,
                price=price_usd,
                cash_available=best_choice["available_cash_usd"],
                fees_estimate=fees_one_way,
                expected_net_edge=net_pct,
                provider_healthy=True,
                metadata={"horizon": horizon, "broker_selected": broker_selected},
            )
        )
        if not risk_result.approved:
            _zero_trade_fields(item)
            item["action"] = _resolve_action(current_qty, 0.0, price_used)
            item["order_side"] = "BUY"
            item["order_status"] = "BLOCKED_RISK"
            _append_constraint(item, "risk_rejected")
            for tag in risk_result.risk_tags:
                _append_constraint(item, f"risk:{tag}")
            item["reason"] = _build_risk_rejected_reason(item.get("_base_reason"), risk_result)
            continue

        _consume_cash_usd(pools, cash_bucket, currency, cash_consumed_usd, fx_rate_used)
        item["usd_target_effective"] = usd_effective
        item["weight"] = (usd_effective / capital) if capital > 0 else 0.0
        item["qty_target"] = qty_target
        item["allow_fractional"] = allow_fractional
        item["fees_estimated_usd"] = fees_round_trip
        item["fees_one_way"] = fees_one_way
        item["fees_round_trip"] = fees_round_trip
        item["broker_costs"] = broker_costs
        item["broker_selected"] = broker_selected
        item["delta_qty"] = delta_qty
        item["expected_return_net_pct"] = net_pct
        item["expected_return_net_usd"] = net_usd
        item["action"] = _resolve_action(current_qty, qty_target, price_used)
        if item["action"] != "BUY":
            item["weight"] = 0.0
            item["usd_target"] = 0.0
            item["usd_target_effective"] = 0.0
            item["order_side"] = None
            item["order_status"] = "NO_ORDER"
            continue
        item["reason"] = _build_reason(
            item.get("_base_reason"),
            gross_pct,
            net_pct,
            threshold,
            bool(item.get("_missing_score")),
            "BUY",
            item.get("min_capital_viable_usd"),
        )
        item["order_side"] = "BUY"
        item["order_qty"] = max(delta_qty, 0.0)
        item["order_notional_usd"] = usd_effective
        item["order_notional_ccy"] = qty_target * (price_used or 0.0)
        item["min_notional_usd"] = min_notional
        item["cash_available_usd"] = best_choice["available_cash_usd"]
        item["cash_used_usd"] = cash_consumed_usd
        item["order_status"] = "CLIPPED_CASH" if best_choice["clipped_cash"] else "READY"

        if currency != "USD" and fx_rate_used is None:
            _append_constraint(item, "fx_rate_missing")
        if usd_effective < best_choice["spend_limit"] - 1e-9:
            _append_constraint(item, "lot_size_rounding")


def _build_risk_engine() -> RiskEngine:
    return RiskEngine(POLICY_RISK_CONFIG)


def _build_risk_rejected_reason(base_reason: str | None, result: RiskCheckResult) -> str:
    parts = []
    if base_reason:
        parts.append(base_reason)
    if result.rejected_reason:
        parts.append(f"risk:{result.rejected_reason}")
    if result.risk_tags:
        parts.append(f"risk_tags={','.join(result.risk_tags)}")
    return " | ".join(parts)


def _append_constraint(item: Dict[str, Any], constraint: str) -> None:
    constraints = item.get("constraints")
    if not isinstance(constraints, list):
        constraints = []
    if constraint not in constraints:
        constraints.append(constraint)
    item["constraints"] = constraints


def _demote_buy(
    items: Dict[str, Dict[str, Any]],
    key: str,
    positions: Dict[str, PositionRecord],
    price_map: Dict[str, float],
    threshold: float,
) -> None:
    item = items[key]
    position = positions.get(key)
    price_used = price_map.get(key)
    current_qty = position.qty if position else 0.0
    item["action"] = _resolve_action(current_qty, 0.0, price_used)
    item["weight"] = 0.0
    item["usd_target"] = 0.0
    if position and price_used is not None:
        meta = get_asset_metadata(key, price_source="features.close")
        currency = item.get("currency") or position.currency or meta.currency
        fx_rate_used, fx_rate_source = _resolve_fx_rate(meta, position)
        price_usd = _price_in_usd(price_used, fx_rate_used)
        sell_value = position.qty * (price_usd or 0.0)
        broker_selected, broker_costs, fees_one_way, fees_round_trip = _select_broker_for_order(
            sell_value,
            currency,
            "equity",
            broker_override=position.broker,
        )
        sell_gross_pct, sell_net_pct, sell_net_usd = _sell_returns(position, price_used, fees_one_way, fx_rate_used)
        item["expected_return_gross_pct"] = sell_gross_pct
        item["expected_return_net_pct"] = sell_net_pct
        item["expected_return_net_usd"] = sell_net_usd
        item["expected_return_source"] = "position_pnl"
        item["fees_estimated_usd"] = fees_one_way
        item["fees_one_way"] = fees_one_way
        item["fees_round_trip"] = fees_round_trip
        item["broker_costs"] = broker_costs
        item["broker_selected"] = broker_selected
        item["current_qty"] = position.qty
        item["usd_target_effective"] = sell_value
        item["qty_target"] = 0.0
        item["delta_qty"] = -position.qty
        item["price_source"] = meta.price_source
        item["currency"] = currency
        item["fx_rate_used"] = fx_rate_used
        item["fx_rate_source"] = fx_rate_source
    else:
        _zero_trade_fields(item)
    item["reason"] = _build_reason(
        item.get("_base_reason"),
        float(item.get("expected_return_gross_pct") or 0.0),
        float(item.get("expected_return_net_pct") or 0.0),
        threshold,
        bool(item.get("_missing_score")),
        item.get("action") or "EXIT",
        item.get("min_capital_viable_usd"),
    )


def _apply_guardrails(
    items: Dict[str, Dict[str, Any]],
    horizon: str,
    capital: float,
    cap: float,
    threshold: float,
    price_map: Dict[str, float],
    positions: Dict[str, PositionRecord],
    cash_by_currency: Dict[str, float] | None,
    cash_by_broker: Dict[str, Dict[str, float]] | None,
) -> None:
    buy_keys = [key for key, item in items.items() if item["action"] == "BUY"]
    if not buy_keys:
        return
    max_positions = MAX_POSITIONS.get(horizon, len(buy_keys))
    if len(buy_keys) > max_positions:
        keep = sorted(
            buy_keys,
            key=lambda key: float(items[key].get("expected_return_net_pct") or 0.0),
            reverse=True,
        )[:max_positions]
        for key in list(buy_keys):
            if key not in keep:
                _demote_buy(items, key, positions, price_map, threshold)
            else:
                _append_constraint(items[key], "max_positions_per_horizon")
        buy_keys = keep
        buy_weights = {key: max(float(items[key].get("weight") or 0.0), 0.0) for key in buy_keys}
        buy_weights = _apply_caps_retain(buy_weights, cap)
        _apply_buy_weights(items, buy_weights, capital, threshold, price_map, positions, cash_by_currency, cash_by_broker, horizon)

    if horizon == "LONG_TERM":
        turnover_cap = MAX_TURNOVER.get("LONG_TERM")
        if turnover_cap is not None:
            while buy_keys and _compute_turnover(items, capital) > turnover_cap:
                worst = min(
                    buy_keys,
                    key=lambda key: float(items[key].get("expected_return_net_pct") or 0.0),
                )
                _demote_buy(items, worst, positions, price_map, threshold)
                buy_keys = [key for key in buy_keys if key != worst]
            if buy_keys:
                for key in buy_keys:
                    _append_constraint(items[key], "max_turnover_long_term")
                buy_weights = {key: max(float(items[key].get("weight") or 0.0), 0.0) for key in buy_keys}
                buy_weights = _apply_caps_retain(buy_weights, cap)
                _apply_buy_weights(
                    items,
                    buy_weights,
                    capital,
                    threshold,
                    price_map,
                    positions,
                    cash_by_currency,
                    cash_by_broker,
                    horizon,
                    None,
                    risk_engine,
                )

    _mark_cap_relaxed(items, cap)


def _mark_cap_relaxed(items: Dict[str, Dict[str, Any]], cap: float) -> None:
    buy_items = [item for item in items.values() if item.get("action") == "BUY"]
    if len(buy_items) == 1:
        item = buy_items[0]
        if float(item.get("weight") or 0.0) > cap:
            _append_constraint(item, "cap_relaxed_single_buy")


def _compute_turnover(items: Dict[str, Dict[str, Any]], capital: float) -> float:
    if capital <= 0:
        return 0.0
    turnover = 0.0
    for item in items.values():
        if item.get("action") != "BUY":
            continue
        target_value = float(item.get("usd_target_effective") or 0.0)
        if target_value <= 0:
            continue
        turnover += target_value / capital
    return turnover


def _action_for_not_recommended(
    position: PositionRecord | None,
    price_used: float | None,
) -> str:
    _ = price_used
    if not position or position.qty <= 0:
        return "SKIP"
    return "SELL"


def _resolve_action(
    current_qty: float,
    target_qty: float,
    price_used: float | None,
) -> str:
    _ = price_used
    if target_qty > current_qty:
        return "BUY"
    if target_qty < current_qty:
        return "SELL"
    if target_qty == 0:
        return "SKIP" if current_qty <= 0 else "EXIT"
    return "HOLD"


def _sell_returns(
    position: PositionRecord,
    price_used: float | None,
    fees: float,
    fx_rate_used: float | None,
) -> Tuple[float, float, float]:
    if price_used is None or position.avg_price <= 0 or position.qty <= 0:
        return 0.0, 0.0, 0.0
    gross_pct = (price_used - position.avg_price) / position.avg_price
    if fx_rate_used is None:
        return gross_pct, 0.0, 0.0
    gross_usd = (price_used - position.avg_price) * position.qty * fx_rate_used
    net_usd = gross_usd - fees
    net_pct = net_usd / (position.avg_price * position.qty * fx_rate_used)
    return gross_pct, net_pct, net_usd


def _sell_returns_for_qty(
    position: PositionRecord,
    price_used: float | None,
    sell_qty: float,
    fees: float,
    fx_rate_used: float | None,
) -> Tuple[float, float, float]:
    if price_used is None or position.avg_price <= 0 or sell_qty <= 0:
        return 0.0, 0.0, 0.0
    gross_pct = (price_used - position.avg_price) / position.avg_price
    if fx_rate_used is None:
        return gross_pct, 0.0, 0.0
    gross_usd = (price_used - position.avg_price) * sell_qty * fx_rate_used
    net_usd = gross_usd - fees
    net_pct = net_usd / (position.avg_price * sell_qty * fx_rate_used)
    return gross_pct, net_pct, net_usd


def _expected_return_gross_pct(candidate: _Candidate, horizon: str) -> Tuple[float, str, bool]:
    if candidate.expected_return_gross_pct is not None:
        value = _clamp_expected_return(candidate.expected_return_gross_pct)
        source = candidate.expected_return_source or "model_regression"
        return value, source, False
    if candidate.model_score is None:
        return 0.0, "proxy_score", True
    score = float(candidate.model_score)
    base = max(0.0, score - 0.5)
    if horizon == "LONG_TERM":
        gross = base * 0.35
        return min(gross, 0.40), "proxy_score", False
    gross = base * 0.20
    return min(gross, 0.20), "proxy_score", False


def _clamp_expected_return(value: float) -> float:
    return max(-1.0, min(float(value), 1.0))


def _compute_qty_and_usd(
    usd_target: float,
    price_used: float | None,
    allow_fractional: bool,
    lot_size: int,
) -> Tuple[float, float]:
    if price_used is None or price_used <= 0 or usd_target <= 0:
        return 0.0, 0.0
    if allow_fractional:
        qty = usd_target / price_used
        return qty, usd_target
    step = max(int(lot_size), 1)
    qty_units = int(usd_target // (price_used * step))
    qty = float(qty_units * step)
    return qty, qty * price_used


def _resolve_fx_rate(meta: Any, position: PositionRecord | None) -> Tuple[float | None, str]:
    if position and position.fx_rate_used is not None:
        return position.fx_rate_used, position.fx_rate_source or "positions_snapshot"
    if getattr(meta, "fx_rate_used", None) is not None:
        return meta.fx_rate_used, meta.fx_rate_source
    return None, "missing"


def _price_in_usd(price_used: float | None, fx_rate_used: float | None) -> float | None:
    if price_used is None:
        return None
    if fx_rate_used is None:
        return None
    return price_used * fx_rate_used


def _to_usd(amount: float, currency: str, fx_rate_used: float | None) -> float | None:
    if currency == "USD":
        return amount
    if fx_rate_used is None or fx_rate_used <= 0:
        return None
    return amount * fx_rate_used


def _from_usd(amount_usd: float, currency: str, fx_rate_used: float | None) -> float | None:
    if currency == "USD":
        return amount_usd
    if fx_rate_used is None or fx_rate_used <= 0:
        return None
    return amount_usd / fx_rate_used


def _build_cash_pools(
    cash_by_currency: Dict[str, float] | None,
    cash_by_broker: Dict[str, Dict[str, float]] | None,
    capital: float,
) -> _CashPools:
    by_currency = {key: float(value) for key, value in (cash_by_currency or {}).items()}
    by_broker = {
        broker: {currency: float(amount) for currency, amount in currencies.items()}
        for broker, currencies in (cash_by_broker or {}).items()
    }
    source = "positions_snapshot" if by_currency or by_broker else "policy_capital"
    return _CashPools(by_broker=by_broker, by_currency=by_currency, fallback_usd=float(capital), source=source)


def _available_cash_usd(
    pools: _CashPools,
    broker: str,
    currency: str,
    fx_rate_used: float | None,
) -> Tuple[float | None, Tuple[str, str]]:
    if broker in pools.by_broker and currency in pools.by_broker[broker]:
        raw_amount = pools.by_broker[broker][currency]
        return _to_usd(raw_amount, currency, fx_rate_used), ("broker", broker)
    if currency in pools.by_currency:
        raw_amount = pools.by_currency[currency]
        return _to_usd(raw_amount, currency, fx_rate_used), ("currency", currency)
    return pools.fallback_usd, ("fallback", "USD")


def _consume_cash_usd(
    pools: _CashPools,
    cash_bucket: Tuple[str, str],
    currency: str,
    usd_amount: float,
    fx_rate_used: float | None,
) -> None:
    kind, key = cash_bucket
    if kind == "fallback":
        pools.fallback_usd = max(0.0, pools.fallback_usd - usd_amount)
        return
    spend_ccy = _from_usd(usd_amount, currency, fx_rate_used)
    if spend_ccy is None:
        return
    if kind == "broker":
        pools.by_broker.setdefault(key, {})
        pools.by_broker[key][currency] = max(0.0, pools.by_broker[key].get(currency, 0.0) - spend_ccy)
    elif kind == "currency":
        pools.by_currency[currency] = max(0.0, pools.by_currency.get(currency, 0.0) - spend_ccy)


def _effective_min_notional_usd(broker: str, horizon: str) -> float:
    policy_min = float(MIN_ORDER_USD.get(horizon, 0.0))
    broker_min = broker_min_notional_usd(broker, "USD")
    return max(policy_min, broker_min)


def _fee_one_way_for_broker(broker: str, usd_amount: float) -> float:
    costs = build_fee_table(usd_amount, brokers=[broker])
    entry = costs.get(broker, {})
    return float(entry.get("fee_one_way") or 0.0)


def _refresh_order_fields(
    item: Dict[str, Any],
    price_map: Dict[str, float],
    positions: Dict[str, PositionRecord],
    horizon: str,
    capital: float,
) -> None:
    _ = capital
    status = item.get("order_status")
    if isinstance(status, str) and status.startswith("BLOCKED"):
        return
    if item.get("action") == "BUY":
        return
    asset_id = item.get("asset_id") or item.get("ticker")
    if not isinstance(asset_id, str) or not asset_id:
        return
    position = positions.get(asset_id)
    meta = get_asset_metadata(asset_id, price_source="features.close")
    currency = item.get("currency") or (position.currency if position else meta.currency)
    price_used = price_map.get(asset_id)
    fx_rate_used, fx_rate_source = _resolve_fx_rate(meta, position)
    price_usd = _price_in_usd(price_used, fx_rate_used)

    item["price_used"] = price_used
    item["price_source"] = meta.price_source
    item["currency"] = currency
    item["fx_rate_used"] = fx_rate_used
    item["fx_rate_source"] = fx_rate_source
    item["lot_size"] = meta.lot_size
    item["allow_fractional"] = meta.allow_fractional
    current_qty = position.qty if position else 0.0
    item["current_qty"] = current_qty
    qty_target = float(item.get("qty_target") or 0.0)
    delta_qty = qty_target - current_qty
    item["delta_qty"] = delta_qty

    if item.get("action") in {"SELL", "EXIT"} and current_qty > 0:
        order_qty = max(current_qty - qty_target, 0.0)
        broker = position.broker if position else (item.get("broker_selected") or DEFAULT_BROKER)
        item["broker_selected"] = broker
        item["order_side"] = "SELL"
        item["order_qty"] = order_qty
        item["order_notional_ccy"] = order_qty * (price_used or 0.0)
        item["order_notional_usd"] = order_qty * (price_usd or 0.0)
        item["min_notional_usd"] = _effective_min_notional_usd(broker, horizon)
        item["usd_target_effective"] = item["order_notional_usd"]
        if position and order_qty > 0 and price_used is not None and price_usd is not None:
            broker_selected, broker_costs, fees_one_way, fees_round_trip = _select_broker_for_order(
                item["order_notional_usd"],
                currency,
                "equity",
                broker_override=broker,
            )
            sell_gross_pct, sell_net_pct, sell_net_usd = _sell_returns_for_qty(
                position,
                price_used,
                order_qty,
                fees_one_way,
                fx_rate_used,
            )
            item["expected_return_gross_pct"] = sell_gross_pct
            item["expected_return_net_pct"] = sell_net_pct
            item["expected_return_net_usd"] = sell_net_usd
            item["expected_return_source"] = "position_pnl"
            item["fees_estimated_usd"] = fees_one_way
            item["fees_one_way"] = fees_one_way
            item["fees_round_trip"] = fees_round_trip
            item["broker_costs"] = broker_costs
            item["broker_selected"] = broker_selected
        if price_usd is None:
            if currency != "USD" and fx_rate_used is None:
                item["order_status"] = "BLOCKED_FX"
                _append_constraint(item, "fx_rate_missing")
            else:
                item["order_status"] = "BLOCKED_PRICE"
                _append_constraint(item, "price_missing")
        elif item["order_notional_usd"] < item["min_notional_usd"]:
            item["order_status"] = "BLOCKED_MIN_NOTIONAL"
            _append_constraint(item, "min_notional")
        else:
            item["order_status"] = "READY"
    else:
        item["order_side"] = None
        item["order_qty"] = 0.0
        item["order_notional_usd"] = 0.0
        item["order_notional_ccy"] = 0.0
        item["min_notional_usd"] = 0.0
        item["order_status"] = "NO_ORDER"


def _select_broker_for_order(
    usd_amount: float,
    currency: str,
    asset_type: str,
    broker_override: str | None = None,
    brokers: List[str] | None = None,
) -> Tuple[str, Dict[str, Any], float, float]:
    broker = broker_override.strip() if isinstance(broker_override, str) and broker_override.strip() else None
    if broker and broker not in BROKER_FRACTIONAL:
        broker = DEFAULT_BROKER
    if broker:
        selection_broker = broker
    else:
        selection = select_broker(usd_amount, currency=currency, asset_type=asset_type, brokers=brokers)
        selection_broker = selection.broker
    costs = build_fee_table(usd_amount, brokers=[selection_broker] if broker else brokers)
    selected = costs.get(selection_broker) or next(
        iter(costs.values()), {"fee_one_way": 0.0, "fee_round_trip": 0.0}
    )
    fee_one_way = float(selected.get("fee_one_way") or 0.0)
    fee_round_trip = float(selected.get("fee_round_trip") or 0.0)
    return selection_broker, costs, fee_one_way, fee_round_trip


def _net_pct(expected_gross_pct: float, fees: float, usd_target: float) -> float:
    if usd_target <= 0:
        return 0.0
    return expected_gross_pct - (fees / usd_target)


def _net_usd(expected_gross_pct: float, fees: float, usd_target: float) -> float:
    return expected_gross_pct * usd_target - fees


def _estimate_min_viable_notional_usd(
    expected_gross_pct: float,
    threshold: float,
    broker_name: str | None,
) -> float | None:
    if not broker_name:
        return None
    margin = float(expected_gross_pct) - float(threshold)
    if margin <= 0:
        return None

    fee_table = build_fee_table(1.0, brokers=[broker_name]).get(broker_name) or {}
    commission_pct = float(fee_table.get("commission_pct") or 0.0)
    min_usd = float(fee_table.get("min_usd") or 0.0)
    min_notional = broker_min_notional_usd(broker_name)

    if commission_pct <= 0:
        if min_usd <= 0:
            return float(min_notional)
        return max(float(min_notional), (2.0 * min_usd) / margin)

    boundary = min_usd / commission_pct if min_usd > 0 else 0.0
    candidate_min_fee = (2.0 * min_usd) / margin if min_usd > 0 else 0.0
    roundtrip_pct_cost = 2.0 * commission_pct

    if min_usd > 0 and candidate_min_fee <= boundary:
        return max(float(min_notional), candidate_min_fee)
    if roundtrip_pct_cost <= margin:
        return max(float(min_notional), boundary)
    return None


def _base_item(
    asset_id: str,
    horizon: str,
    action: str,
    weight: float,
    usd_target: float,
    usd_target_effective: float,
    qty_target: float,
    price_used: float | None,
    price_source: str,
    currency: str,
    fx_rate_used: float | None,
    fx_rate_source: str,
    lot_size: int,
    allow_fractional: bool,
    expected_return_gross_pct: float,
    expected_return_net_pct: float,
    expected_return_net_usd: float,
    expected_return_source: str,
    fees_estimated_usd: float,
    fees_one_way: float,
    fees_round_trip: float,
    broker_costs: Dict[str, Any],
    reason: str,
    asof_date: str | None,
    execution_date: str | None,
    execution_hour: str | None,
    broker_selected: str,
    current_qty: float,
    delta_qty: float,
    min_capital_viable_usd: float | None,
) -> Dict[str, Any]:
    return {
        "ticker": asset_id,
        "asset_id": asset_id,
        "horizon": horizon,
        "action": action,
        "weight": weight,
        "usd_target": usd_target,
        "usd_target_effective": usd_target_effective,
        "broker_selected": broker_selected,
        "current_qty": current_qty,
        "qty_target": qty_target,
        "delta_qty": delta_qty,
        "order_side": None,
        "order_type": ORDER_TYPE_DEFAULT,
        "time_in_force": TIME_IN_FORCE_DEFAULT,
        "order_qty": 0.0,
        "order_notional_usd": 0.0,
        "order_notional_ccy": 0.0,
        "min_notional_usd": 0.0,
        "order_status": "NO_ORDER",
        "cash_available_usd": None,
        "cash_used_usd": 0.0,
        "min_capital_viable_usd": min_capital_viable_usd,
        "price_used": price_used,
        "price_source": price_source,
        "currency": currency,
        "fx_rate_used": fx_rate_used,
        "fx_rate_source": fx_rate_source,
        "lot_size": lot_size,
        "allow_fractional": allow_fractional,
        "expected_return_gross_pct": expected_return_gross_pct,
        "expected_return_net_pct": expected_return_net_pct,
        "expected_return_net_usd": expected_return_net_usd,
        "expected_return_source": expected_return_source,
        "fees_estimated_usd": fees_estimated_usd,
        "fees_one_way": fees_one_way,
        "fees_round_trip": fees_round_trip,
        "broker_costs": broker_costs,
        "reason": reason,
        "policy_id": POLICY_ID,
        "policy_version": POLICY_VERSION,
        "constraints": [],
        "sizing_rule": "weights.normalized_pct",
        "asof_date": asof_date,
        "execution_date": execution_date,
        "execution_hour": execution_hour,
    }


def _override_for_position(item: Dict[str, Any], position: PositionRecord, price_used: float | None) -> None:
    fx_rate_used = position.fx_rate_used
    if fx_rate_used is None and (position.currency or "USD") == "USD":
        fx_rate_used = 1.0
    sell_value = position.qty * (_price_in_usd(price_used, fx_rate_used) or 0.0)
    broker_selected, broker_costs, fees_one_way, fees_round_trip = _select_broker_for_order(
        sell_value,
        position.currency or "USD",
        "equity",
        broker_override=position.broker,
    )
    gross_pct, net_pct, net_usd = _sell_returns(position, price_used, fees_one_way, fx_rate_used)
    item["usd_target_effective"] = sell_value
    item["qty_target"] = position.qty
    item["fees_estimated_usd"] = fees_one_way
    item["fees_one_way"] = fees_one_way
    item["fees_round_trip"] = fees_round_trip
    item["broker_costs"] = broker_costs
    item["broker_selected"] = broker_selected
    item["expected_return_gross_pct"] = gross_pct
    item["expected_return_net_pct"] = net_pct
    item["expected_return_net_usd"] = net_usd


def _override_for_hold(
    item: Dict[str, Any],
    position: PositionRecord,
    price_used: float | None,
    expected_gross_pct: float,
) -> None:
    if price_used is None or position.qty <= 0:
        return
    usd_effective = position.qty * price_used
    item["usd_target_effective"] = usd_effective
    item["qty_target"] = position.qty
    item["fees_estimated_usd"] = 0.0
    item["fees_one_way"] = 0.0
    item["fees_round_trip"] = 0.0
    item["expected_return_net_pct"] = expected_gross_pct
    item["expected_return_net_usd"] = expected_gross_pct * usd_effective


def _zero_trade_fields(item: Dict[str, Any]) -> None:
    item["weight"] = 0.0
    item["usd_target"] = 0.0
    item["usd_target_effective"] = 0.0
    item["qty_target"] = 0.0
    item["delta_qty"] = 0.0
    item["fees_estimated_usd"] = 0.0
    item["fees_one_way"] = 0.0
    item["fees_round_trip"] = 0.0
    item["expected_return_net_pct"] = 0.0
    item["expected_return_net_usd"] = 0.0
    item["order_side"] = None
    item["order_qty"] = 0.0
    item["order_notional_usd"] = 0.0
    item["order_notional_ccy"] = 0.0
    item["min_notional_usd"] = 0.0
    item["order_status"] = "NO_ORDER"
    item["cash_available_usd"] = None
    item["cash_used_usd"] = 0.0


def _build_reason(
    base_reason: str | None,
    expected_gross_pct: float,
    expected_net_pct: float,
    threshold: float,
    missing_score: bool,
    action: str,
    min_capital_viable_usd: float | None,
) -> str:
    parts = []
    if missing_score:
        parts.append("model_score missing -> gross_pct=0")
    if base_reason:
        parts.append(base_reason)
    parts.append(f"gross_pct={expected_gross_pct:.6f}")
    parts.append(f"net_pct={expected_net_pct:.6f}")
    parts.append(f"threshold={threshold:.6f}")
    if min_capital_viable_usd is not None:
        parts.append(f"min_capital_viable_usd={min_capital_viable_usd:.2f}")
    elif action in {"EXIT", "SKIP"} and expected_gross_pct > 0:
        parts.append("broker_cost_floor>edge")
    if action in {"EXIT", "SKIP"}:
        parts.append("net<threshold")
    return " | ".join(parts)


def _normalize_weights(weights: Dict[str, float]) -> Dict[str, float]:
    total = sum(max(weight, 0.0) for weight in weights.values())
    if total <= 0 and weights:
        equal = 1.0 / len(weights)
        return {key: equal for key in weights}
    if total <= 0:
        return {key: 0.0 for key in weights}
    return {key: max(weight, 0.0) / total for key, weight in weights.items()}


def _apply_caps(weights: Dict[str, float], cap: float, max_iters: int = 2) -> Dict[str, float]:
    adjusted = dict(weights)
    for _ in range(max_iters):
        over = {key: weight for key, weight in adjusted.items() if weight > cap}
        if not over:
            break
        capped_sum = cap * len(over)
        rest = {key: weight for key, weight in adjusted.items() if key not in over}
        rest_sum = sum(rest.values())
        if capped_sum >= 1.0 or rest_sum <= 0:
            scale = 1.0 / capped_sum if capped_sum > 0 else 0.0
            adjusted = {key: cap * scale for key in over}
            for key in rest:
                adjusted[key] = 0.0
            break
        remaining = 1.0 - capped_sum
        scale = remaining / rest_sum
        adjusted = {
            key: (cap if key in over else weight * scale)
            for key, weight in adjusted.items()
        }
    return adjusted


def _apply_caps_retain(weights: Dict[str, float], cap: float) -> Dict[str, float]:
    if len(weights) == 1:
        return {key: max(weight, 0.0) for key, weight in weights.items()}
    return {key: min(max(weight, 0.0), cap) for key, weight in weights.items()}


def _clean_asset_id(value: Any) -> str:
    if not value:
        return ""
    return str(value).strip().upper()


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
