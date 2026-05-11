from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


def _serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value


@dataclass(frozen=True)
class CryptoPaperExecutionConfig:
    starting_cash: float = 100.0
    quote_currency: str = "USDT"
    fee_bps: float = 10.0
    slippage_bps: float = 5.0
    max_notional_per_order: float = 25.0
    min_notional_per_order: float = 5.0
    allow_fractional_quantity: bool = True
    allow_short: bool = False
    allow_live_trading: bool = False
    enable_exits: bool = False
    exit_full_position: bool = True
    conservative_same_candle_policy: str = "stop_loss_first"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CryptoPaperOrder:
    order_id: str
    symbol: str
    side: str
    requested_notional: float
    requested_quantity: float | None
    reference_price: float
    status: str
    reason: str | None
    created_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True)
class CryptoPaperFill:
    fill_id: str
    order_id: str
    symbol: str
    side: str
    quantity: float
    fill_price: float
    gross_notional: float
    fee: float
    slippage: float
    net_notional: float
    filled_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True)
class CryptoPaperExitEvent:
    exit_id: str
    symbol: str
    position_quantity_before: float
    exit_quantity: float
    exit_reason: str
    trigger_price: float
    fill_price: float
    gross_notional: float
    fee: float
    slippage: float
    realized_pnl: float
    exited_at: datetime
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True)
class CryptoPaperPosition:
    symbol: str
    quantity: float
    avg_entry_price: float
    realized_pnl: float
    unrealized_pnl: float
    last_price: float | None
    updated_at: datetime | None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True)
class CryptoPaperPortfolioSnapshot:
    as_of: datetime
    cash: float
    equity: float
    positions_value: float
    realized_pnl: float
    unrealized_pnl: float
    fees_paid: float
    positions: list[CryptoPaperPosition]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True)
class CryptoPaperExecutionResult:
    accepted_orders: list[CryptoPaperOrder]
    rejected_orders: list[CryptoPaperOrder]
    fills: list[CryptoPaperFill]
    portfolio_snapshot: CryptoPaperPortfolioSnapshot
    warnings: list[str] = field(default_factory=list)
    exit_events: list[CryptoPaperExitEvent] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))
