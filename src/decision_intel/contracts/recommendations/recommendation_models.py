from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .recommendation_constants import RECOMMENDATION_READER_MIN_VERSION, RECOMMENDATION_SCHEMA_VERSION


_ITEM_KNOWN_FIELDS = {
    "ticker",
    "asset_id",
    "horizon",
    "action",
    "weight",
    "usd_target",
    "usd_target_effective",
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
    "min_capital_viable_usd",
    "price_used",
    "price_source",
    "currency",
    "fx_rate_used",
    "fx_rate_source",
    "lot_size",
    "allow_fractional",
    "expected_return_gross_pct",
    "expected_return_net_pct",
    "expected_return_net_usd",
    "expected_return_source",
    "fees_estimated_usd",
    "fees_one_way",
    "fees_round_trip",
    "broker_costs",
    "reason",
    "policy_id",
    "policy_version",
    "constraints",
    "sizing_rule",
    "asof_date",
    "execution_date",
    "execution_hour",
}


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "si", "s"}
    return bool(value)


def _as_str(value: Any) -> str:
    return str(value or "")


def _as_optional_str(value: Any) -> Optional[str]:
    text = _as_str(value).strip()
    return text or None


@dataclass(frozen=True)
class RecommendationItem:
    ticker: str
    asset_id: str
    horizon: str
    action: str
    weight: float
    usd_target: float
    usd_target_effective: float
    broker_selected: str
    current_qty: float
    qty_target: float
    delta_qty: float
    order_side: Optional[str]
    order_type: str
    time_in_force: str
    order_qty: float
    order_notional_usd: float
    order_notional_ccy: float
    min_notional_usd: float
    order_status: str
    cash_available_usd: Optional[float]
    cash_used_usd: float
    min_capital_viable_usd: Optional[float]
    price_used: Optional[float]
    price_source: str
    currency: str
    fx_rate_used: Optional[float]
    fx_rate_source: str
    lot_size: int
    allow_fractional: bool
    expected_return_gross_pct: float
    expected_return_net_pct: float
    expected_return_net_usd: float
    expected_return_source: str
    fees_estimated_usd: float
    fees_one_way: float
    fees_round_trip: float
    broker_costs: Dict[str, Any]
    reason: str
    policy_id: str
    policy_version: str
    constraints: List[str]
    sizing_rule: str
    asof_date: Optional[str] = None
    execution_date: Optional[str] = None
    execution_hour: Optional[str] = None
    extensions: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, row: Dict[str, Any]) -> "RecommendationItem":
        extras = {key: value for key, value in row.items() if key not in _ITEM_KNOWN_FIELDS}
        return cls(
            ticker=_as_str(row.get("ticker") or row.get("asset_id")).strip().upper(),
            asset_id=_as_str(row.get("asset_id") or row.get("ticker")).strip().upper(),
            horizon=_as_str(row.get("horizon")).strip().upper(),
            action=_as_str(row.get("action")).strip().upper(),
            weight=_as_float(row.get("weight")),
            usd_target=_as_float(row.get("usd_target")),
            usd_target_effective=_as_float(row.get("usd_target_effective")),
            broker_selected=_as_str(row.get("broker_selected")),
            current_qty=_as_float(row.get("current_qty")),
            qty_target=_as_float(row.get("qty_target")),
            delta_qty=_as_float(row.get("delta_qty")),
            order_side=_as_optional_str(row.get("order_side")),
            order_type=_as_str(row.get("order_type")),
            time_in_force=_as_str(row.get("time_in_force")),
            order_qty=_as_float(row.get("order_qty")),
            order_notional_usd=_as_float(row.get("order_notional_usd")),
            order_notional_ccy=_as_float(row.get("order_notional_ccy")),
            min_notional_usd=_as_float(row.get("min_notional_usd")),
            order_status=_as_str(row.get("order_status")),
            cash_available_usd=_as_optional_float(row.get("cash_available_usd")),
            cash_used_usd=_as_float(row.get("cash_used_usd")),
            min_capital_viable_usd=_as_optional_float(row.get("min_capital_viable_usd")),
            price_used=_as_optional_float(row.get("price_used")),
            price_source=_as_str(row.get("price_source")),
            currency=_as_str(row.get("currency")).strip().upper(),
            fx_rate_used=_as_optional_float(row.get("fx_rate_used")),
            fx_rate_source=_as_str(row.get("fx_rate_source")),
            lot_size=_as_int(row.get("lot_size"), default=1),
            allow_fractional=_as_bool(row.get("allow_fractional")),
            expected_return_gross_pct=_as_float(row.get("expected_return_gross_pct")),
            expected_return_net_pct=_as_float(row.get("expected_return_net_pct")),
            expected_return_net_usd=_as_float(row.get("expected_return_net_usd")),
            expected_return_source=_as_str(row.get("expected_return_source")),
            fees_estimated_usd=_as_float(row.get("fees_estimated_usd")),
            fees_one_way=_as_float(row.get("fees_one_way")),
            fees_round_trip=_as_float(row.get("fees_round_trip")),
            broker_costs=dict(row.get("broker_costs") or {}),
            reason=_as_str(row.get("reason")),
            policy_id=_as_str(row.get("policy_id")),
            policy_version=_as_str(row.get("policy_version")),
            constraints=[_as_str(item) for item in (row.get("constraints") or [])],
            sizing_rule=_as_str(row.get("sizing_rule")),
            asof_date=_as_optional_str(row.get("asof_date")),
            execution_date=_as_optional_str(row.get("execution_date")),
            execution_hour=_as_optional_str(row.get("execution_hour")),
            extensions=extras,
        )

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "ticker": self.ticker,
            "asset_id": self.asset_id,
            "horizon": self.horizon,
            "action": self.action,
            "weight": self.weight,
            "usd_target": self.usd_target,
            "usd_target_effective": self.usd_target_effective,
            "broker_selected": self.broker_selected,
            "current_qty": self.current_qty,
            "qty_target": self.qty_target,
            "delta_qty": self.delta_qty,
            "order_side": self.order_side,
            "order_type": self.order_type,
            "time_in_force": self.time_in_force,
            "order_qty": self.order_qty,
            "order_notional_usd": self.order_notional_usd,
            "order_notional_ccy": self.order_notional_ccy,
            "min_notional_usd": self.min_notional_usd,
            "order_status": self.order_status,
            "cash_available_usd": self.cash_available_usd,
            "cash_used_usd": self.cash_used_usd,
            "min_capital_viable_usd": self.min_capital_viable_usd,
            "price_used": self.price_used,
            "price_source": self.price_source,
            "currency": self.currency,
            "fx_rate_used": self.fx_rate_used,
            "fx_rate_source": self.fx_rate_source,
            "lot_size": self.lot_size,
            "allow_fractional": self.allow_fractional,
            "expected_return_gross_pct": self.expected_return_gross_pct,
            "expected_return_net_pct": self.expected_return_net_pct,
            "expected_return_net_usd": self.expected_return_net_usd,
            "expected_return_source": self.expected_return_source,
            "fees_estimated_usd": self.fees_estimated_usd,
            "fees_one_way": self.fees_one_way,
            "fees_round_trip": self.fees_round_trip,
            "broker_costs": self.broker_costs,
            "reason": self.reason,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "constraints": list(self.constraints),
            "sizing_rule": self.sizing_rule,
            "asof_date": self.asof_date,
            "execution_date": self.execution_date,
            "execution_hour": self.execution_hour,
        }
        payload.update(self.extensions)
        return payload


@dataclass(frozen=True)
class RecommendationOutput:
    schema_version: str
    reader_min_version: str
    run_id: str
    horizon: Optional[str]
    asof_date: Optional[str]
    policy_id: str
    policy_version: str
    constraints: List[str]
    sizing_rule: str
    recommendations: List[RecommendationItem]
    cash_summary: Dict[str, Dict[str, Any]]
    cash_policy: str
    execution_date: Optional[str] = None
    execution_hour: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        run_id: str,
        horizon: Optional[str],
        asof_date: Optional[str],
        policy_id: str,
        policy_version: str,
        constraints: List[str],
        sizing_rule: str,
        recommendations: List[Dict[str, Any]] | List[RecommendationItem],
        cash_summary: Dict[str, Dict[str, Any]],
        cash_policy: str,
        execution_date: Optional[str] = None,
        execution_hour: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "RecommendationOutput":
        items = [
            item if isinstance(item, RecommendationItem) else RecommendationItem.from_dict(item)
            for item in recommendations
        ]
        return cls(
            schema_version=RECOMMENDATION_SCHEMA_VERSION,
            reader_min_version=RECOMMENDATION_READER_MIN_VERSION,
            run_id=run_id,
            horizon=horizon,
            asof_date=asof_date,
            policy_id=policy_id,
            policy_version=policy_version,
            constraints=list(constraints),
            sizing_rule=sizing_rule,
            recommendations=items,
            cash_summary=cash_summary,
            cash_policy=cash_policy,
            execution_date=execution_date,
            execution_hour=execution_hour,
            metadata=dict(metadata or {}),
        )

    def to_payload(self) -> Dict[str, Any]:
        payload = {
            "schema_version": self.schema_version,
            "reader_min_version": self.reader_min_version,
            "run_id": self.run_id,
            "horizon": self.horizon,
            "asof_date": self.asof_date,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "constraints": list(self.constraints),
            "sizing_rule": self.sizing_rule,
            "recommendations": [item.to_dict() for item in self.recommendations],
            "cash_summary": self.cash_summary,
            "cash_policy": self.cash_policy,
            "execution_date": self.execution_date,
            "execution_hour": self.execution_hour,
        }
        payload.update(self.metadata)
        return payload
