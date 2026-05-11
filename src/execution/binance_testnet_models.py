"""Dataclasses for the Binance Spot **Testnet** execution layer.

Mirrors the shape of :mod:`src.execution.crypto_paper_models` so the
testnet artifact files are easy to reason about side-by-side with the
paper artifacts. Testnet artifacts are written under
``artifacts/crypto_testnet/`` and never replace paper artifacts.
"""

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
class BinanceTestnetExecutionConfig:
    """Static safety-critical config for the testnet executor."""

    base_url: str = "https://testnet.binance.vision"
    quote_currency: str = "USDT"
    max_notional_per_order: float = 25.0
    allowed_symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT")
    order_type_default: str = "MARKET"
    order_test_only: bool = True
    enable_testnet_execution: bool = False
    exit_full_position: bool = True
    recv_window_ms: int = 5000

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["allowed_symbols"] = list(self.allowed_symbols)
        return payload


@dataclass(frozen=True)
class BinanceTestnetOrder:
    """A testnet order request (order/test or real)."""

    client_order_id: str
    symbol: str
    side: str
    type: str
    quantity: float | None
    quote_order_qty: float | None
    requested_notional: float
    reference_price: float | None
    paper_event_id: str
    paper_event_type: str
    mode: str  # "order_test" or "place_order"
    status: str  # "ACCEPTED", "REJECTED", "TEST_OK", "FILLED", etc.
    reason: str | None
    created_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True)
class BinanceTestnetFill:
    """A testnet fill returned by Binance after order placement."""

    fill_id: str
    client_order_id: str
    binance_order_id: int | str
    symbol: str
    side: str
    quantity: float
    price: float
    commission: float
    commission_asset: str
    status: str
    transact_time_ms: int | None
    filled_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True)
class BinanceTestnetPosition:
    """A locally-derived testnet position (we don't margin-trade; this is just
    spot inventory tracked from observed fills)."""

    symbol: str
    quantity: float
    avg_entry_price: float
    last_event_at: datetime | None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True)
class BinanceTestnetReconciliationItem:
    """One paper-vs-testnet semantic comparison row."""

    paper_event_id: str
    paper_event_type: str
    symbol: str
    paper_side: str
    expected_notional: float | None
    testnet_client_order_id: str | None
    testnet_status: str | None
    testnet_mode: str | None
    match: bool
    mismatches: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True)
class BinanceTestnetExecutionResult:
    """Top-level result of one testnet executor run."""

    accepted_orders: list[BinanceTestnetOrder]
    rejected_orders: list[BinanceTestnetOrder]
    fills: list[BinanceTestnetFill]
    positions: list[BinanceTestnetPosition]
    reconciliation: list[BinanceTestnetReconciliationItem]
    skipped: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


__all__ = [
    "BinanceTestnetExecutionConfig",
    "BinanceTestnetExecutionResult",
    "BinanceTestnetFill",
    "BinanceTestnetOrder",
    "BinanceTestnetPosition",
    "BinanceTestnetReconciliationItem",
]
