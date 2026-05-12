"""Manual portfolio state loader.

Read-only. No network. No broker. No API keys. Manual review only.

The portfolio snapshot is a local JSON file that captures current holdings
(quantities, average cost, bucket assignment) for valuation against a separate
market snapshot. It is explicitly *manual*; the loader never places orders.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from src.market_data.ar_symbols import normalize_ar_symbol


_REQUIRED_TOP_LEVEL_FIELDS = (
    "schema_version",
    "snapshot_id",
    "as_of",
    "source",
    "base_currency",
    "manual_review_only",
    "live_trading_enabled",
    "cash",
    "positions",
)

_VALID_COMPLETENESS = {"complete", "partial", "minimal", "unknown"}


@dataclass(frozen=True)
class CashBalance:
    currency: str
    amount: float
    bucket: str
    notes: str = ""


@dataclass(frozen=True)
class PortfolioPosition:
    symbol: str
    asset_class: str
    quantity: float
    average_cost: Optional[float]
    average_cost_currency: Optional[str]
    market: str
    bucket: str
    notes: str = ""


@dataclass(frozen=True)
class ManualPortfolioSnapshot:
    schema_version: str
    snapshot_id: str
    as_of: str
    source: str
    base_currency: str
    manual_review_only: bool
    live_trading_enabled: bool
    cash: tuple = field(default_factory=tuple)
    positions: tuple = field(default_factory=tuple)
    warnings: tuple = field(default_factory=tuple)
    completeness: str = "unknown"


def _coerce_float(value: Any, *, field_name: str, ctx: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{ctx}: {field_name} must be numeric") from exc


def _validate_top_level(data: Mapping[str, Any], path: Path) -> None:
    if not isinstance(data, Mapping):
        raise ValueError(f"{path}: portfolio snapshot must be an object")
    for name in _REQUIRED_TOP_LEVEL_FIELDS:
        if name not in data:
            raise ValueError(f"{path}: missing top-level field {name!r}")
    if data.get("manual_review_only") is not True:
        raise ValueError(f"{path}: manual_review_only must be true")
    if data.get("live_trading_enabled") is not False:
        raise ValueError(f"{path}: live_trading_enabled must be false")
    if not isinstance(data.get("cash"), list):
        raise ValueError(f"{path}: cash must be a list")
    if not isinstance(data.get("positions"), list):
        raise ValueError(f"{path}: positions must be a list")


def _parse_cash(items: Iterable[Mapping[str, Any]], path: Path) -> tuple[CashBalance, ...]:
    out: list[CashBalance] = []
    for index, raw in enumerate(items):
        if not isinstance(raw, Mapping):
            raise ValueError(f"{path}: cash[{index}] must be an object")
        for required in ("currency", "amount", "bucket"):
            if required not in raw:
                raise ValueError(
                    f"{path}: cash[{index}] missing required field {required!r}"
                )
        currency = str(raw["currency"]).strip().upper()
        if not currency:
            raise ValueError(f"{path}: cash[{index}] currency must not be empty")
        amount = _coerce_float(
            raw["amount"], field_name="amount", ctx=f"{path}: cash[{index}]"
        )
        if amount < 0:
            raise ValueError(
                f"{path}: cash[{index}] amount must be >= 0 (got {amount})"
            )
        out.append(
            CashBalance(
                currency=currency,
                amount=amount,
                bucket=str(raw["bucket"]),
                notes=str(raw.get("notes", "")),
            )
        )
    return tuple(out)


def _parse_positions(
    items: Iterable[Mapping[str, Any]], path: Path
) -> tuple[PortfolioPosition, ...]:
    out: list[PortfolioPosition] = []
    for index, raw in enumerate(items):
        if not isinstance(raw, Mapping):
            raise ValueError(f"{path}: positions[{index}] must be an object")
        for required in ("symbol", "asset_class", "quantity", "market", "bucket"):
            if required not in raw:
                raise ValueError(
                    f"{path}: positions[{index}] missing required field {required!r}"
                )
        symbol = normalize_ar_symbol(str(raw["symbol"]))
        quantity = _coerce_float(
            raw["quantity"], field_name="quantity", ctx=f"{path}: positions[{symbol!r}]"
        )
        if quantity <= 0:
            raise ValueError(
                f"{path}: positions[{symbol!r}] quantity must be > 0 (got {quantity})"
            )
        avg_cost_raw = raw.get("average_cost", None)
        if avg_cost_raw is None:
            avg_cost: Optional[float] = None
        else:
            avg_cost = _coerce_float(
                avg_cost_raw,
                field_name="average_cost",
                ctx=f"{path}: positions[{symbol!r}]",
            )
            if avg_cost < 0:
                raise ValueError(
                    f"{path}: positions[{symbol!r}] average_cost must be >= 0"
                )
        avg_cost_currency_raw = raw.get("average_cost_currency", None)
        avg_cost_currency = (
            str(avg_cost_currency_raw).strip().upper()
            if avg_cost_currency_raw is not None
            else None
        )
        out.append(
            PortfolioPosition(
                symbol=symbol,
                asset_class=str(raw["asset_class"]),
                quantity=quantity,
                average_cost=avg_cost,
                average_cost_currency=avg_cost_currency or None,
                market=str(raw["market"]),
                bucket=str(raw["bucket"]),
                notes=str(raw.get("notes", "")),
            )
        )
    return tuple(out)


def _parse_quality(data: Mapping[str, Any], path: Path) -> tuple[tuple[str, ...], str]:
    quality = data.get("quality")
    if quality is None:
        return tuple(), "unknown"
    if not isinstance(quality, Mapping):
        raise ValueError(f"{path}: quality must be an object if present")
    warnings_raw = quality.get("warnings", [])
    if warnings_raw is None:
        warnings: tuple[str, ...] = tuple()
    elif isinstance(warnings_raw, list):
        warnings = tuple(str(w) for w in warnings_raw)
    else:
        raise ValueError(f"{path}: quality.warnings must be a list when present")
    completeness = str(quality.get("completeness", "unknown")).strip().lower()
    if completeness not in _VALID_COMPLETENESS:
        completeness = "unknown"
    return warnings, completeness


def load_manual_portfolio_snapshot(path: str | Path) -> ManualPortfolioSnapshot:
    config_path = Path(path)
    if not config_path.exists():
        raise ValueError(f"manual portfolio snapshot not found: {config_path}")
    try:
        with config_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{config_path}: invalid JSON: {exc}") from exc

    _validate_top_level(data, config_path)

    cash = _parse_cash(data["cash"], config_path)
    positions = _parse_positions(data["positions"], config_path)
    warnings, completeness = _parse_quality(data, config_path)

    return ManualPortfolioSnapshot(
        schema_version=str(data["schema_version"]),
        snapshot_id=str(data["snapshot_id"]),
        as_of=str(data["as_of"]),
        source=str(data["source"]),
        base_currency=str(data["base_currency"]).strip().upper() or "USD",
        manual_review_only=True,
        live_trading_enabled=False,
        cash=cash,
        positions=positions,
        warnings=warnings,
        completeness=completeness,
    )


def get_position_by_symbol(
    snapshot: ManualPortfolioSnapshot, symbol: str
) -> Optional[PortfolioPosition]:
    if not isinstance(symbol, str) or not symbol.strip():
        return None
    target = normalize_ar_symbol(symbol)
    for position in snapshot.positions:
        if position.symbol == target:
            return position
    return None


def summarize_portfolio_snapshot(snapshot: ManualPortfolioSnapshot) -> dict[str, Any]:
    return {
        "snapshot_id": snapshot.snapshot_id,
        "as_of": snapshot.as_of,
        "base_currency": snapshot.base_currency,
        "positions_loaded": len(snapshot.positions),
        "cash_balances_loaded": len(snapshot.cash),
        "warnings": list(snapshot.warnings),
        "completeness": snapshot.completeness,
    }


__all__ = [
    "CashBalance",
    "PortfolioPosition",
    "ManualPortfolioSnapshot",
    "load_manual_portfolio_snapshot",
    "get_position_by_symbol",
    "summarize_portfolio_snapshot",
]
