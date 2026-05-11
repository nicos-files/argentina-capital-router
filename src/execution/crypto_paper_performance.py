from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from .crypto_paper_models import CryptoPaperPortfolioSnapshot, CryptoPaperPosition


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
class CryptoPaperPerformanceSummary:
    as_of: datetime
    starting_cash: float
    ending_cash: float
    starting_equity: float
    ending_equity: float
    positions_value: float
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    total_return_pct: float
    fees_paid: float
    fills_count: int
    accepted_orders_count: int
    rejected_orders_count: int
    open_positions_count: int
    symbols_held: list[str]
    best_position: dict[str, Any] | None
    worst_position: dict[str, Any] | None
    exit_events_count: int = 0
    data_quality_warnings: list[str] = field(default_factory=list)
    provider_health: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    paper_only: bool = True
    live_trading: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


def compute_crypto_paper_performance(
    *,
    as_of: datetime,
    positions: list[CryptoPaperPosition],
    ending_cash: float,
    current_snapshot: CryptoPaperPortfolioSnapshot | None = None,
    previous_snapshot: CryptoPaperPortfolioSnapshot | None = None,
    starting_cash: float = 100.0,
    fills_count: int = 0,
    accepted_orders_count: int = 0,
    rejected_orders_count: int = 0,
    exit_events_count: int = 0,
    warnings: list[str] | None = None,
    provider_health: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> CryptoPaperPerformanceSummary:
    warnings_list = list(warnings or [])
    held_positions = [position for position in positions if float(position.quantity) > 0.0]
    positions_value = sum(_position_value(position) for position in held_positions)
    unrealized_pnl = sum(float(position.unrealized_pnl or 0.0) for position in held_positions)
    realized_pnl = _resolved_realized_pnl(current_snapshot, held_positions)
    fees_paid = _resolved_fees_paid(current_snapshot)

    if previous_snapshot is not None:
        starting_cash_value = float(previous_snapshot.cash)
        starting_equity = float(previous_snapshot.equity)
    else:
        starting_cash_value = float(starting_cash)
        starting_equity = float(starting_cash)

    ending_cash_value = float(current_snapshot.cash) if current_snapshot is not None else float(ending_cash)
    ending_equity = float(ending_cash_value) + float(positions_value)
    total_pnl = float(ending_equity) - float(starting_equity)
    total_return_pct = (total_pnl / starting_equity) if abs(starting_equity) > 1e-12 else 0.0

    best_position = _position_extreme(held_positions, reverse=True)
    worst_position = _position_extreme(held_positions, reverse=False)

    return CryptoPaperPerformanceSummary(
        as_of=as_of,
        starting_cash=float(starting_cash_value),
        ending_cash=float(ending_cash_value),
        starting_equity=float(starting_equity),
        ending_equity=float(ending_equity),
        positions_value=float(positions_value),
        realized_pnl=float(realized_pnl),
        unrealized_pnl=float(unrealized_pnl),
        total_pnl=float(total_pnl),
        total_return_pct=float(total_return_pct),
        fees_paid=float(fees_paid),
        fills_count=int(fills_count),
        accepted_orders_count=int(accepted_orders_count),
        rejected_orders_count=int(rejected_orders_count),
        open_positions_count=len(held_positions),
        symbols_held=sorted(position.symbol for position in held_positions),
        exit_events_count=int(exit_events_count),
        best_position=best_position,
        worst_position=worst_position,
        data_quality_warnings=warnings_list,
        provider_health=dict(provider_health or {}),
        metadata=dict(metadata or {}),
    )


def _position_value(position: CryptoPaperPosition) -> float:
    mark = position.last_price if position.last_price is not None else position.avg_entry_price
    return float(mark or 0.0) * float(position.quantity or 0.0)


def _resolved_realized_pnl(
    current_snapshot: CryptoPaperPortfolioSnapshot | None,
    positions: list[CryptoPaperPosition],
) -> float:
    if current_snapshot is not None:
        return float(current_snapshot.realized_pnl or 0.0)
    return sum(float(position.realized_pnl or 0.0) for position in positions)


def _resolved_fees_paid(current_snapshot: CryptoPaperPortfolioSnapshot | None) -> float:
    if current_snapshot is None:
        return 0.0
    return float(current_snapshot.fees_paid or 0.0)


def _position_extreme(positions: list[CryptoPaperPosition], reverse: bool) -> dict[str, Any] | None:
    if not positions:
        return None
    selected = sorted(
        positions,
        key=lambda position: (float(position.unrealized_pnl or 0.0), position.symbol),
        reverse=reverse,
    )[0]
    basis = float(selected.avg_entry_price or 0.0) * float(selected.quantity or 0.0)
    return {
        "symbol": selected.symbol,
        "quantity": float(selected.quantity or 0.0),
        "avg_entry_price": float(selected.avg_entry_price or 0.0),
        "last_price": float(selected.last_price) if selected.last_price is not None else None,
        "position_value": _position_value(selected),
        "unrealized_pnl": float(selected.unrealized_pnl or 0.0),
        "unrealized_pnl_pct": (float(selected.unrealized_pnl or 0.0) / basis) if abs(basis) > 1e-12 else 0.0,
    }
