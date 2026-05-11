from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.decision_intel.contracts.recommendations.recommendation_models import RecommendationOutput
from src.decision_intel.utils.io import ensure_run_dir
from src.market_data.crypto_symbols import is_crypto_symbol, normalize_crypto_symbol
from src.risk import RiskCheckInput, RiskEngine

from .crypto_paper_ledger import CryptoPaperLedger
from .crypto_paper_models import CryptoPaperExitEvent, CryptoPaperPosition
from .crypto_paper_models import (
    CryptoPaperExecutionConfig,
    CryptoPaperExecutionResult,
    CryptoPaperFill,
    CryptoPaperOrder,
)


def format_id_stamp(value: datetime | None) -> str:
    """Return a compact UTC stamp ``YYYYMMDDTHHMMSS`` used in artifact IDs.

    Used to make fill_id/order_id/exit_id globally unique across runs so that
    cumulative artifact merging never silently drops historical records.
    """

    moment = value if isinstance(value, datetime) else utc_now()
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment.strftime("%Y%m%dT%H%M%S")


class CryptoPaperExecutor:
    def __init__(
        self,
        config: CryptoPaperExecutionConfig | None = None,
        risk_engine: RiskEngine | None = None,
    ):
        self.config = config or CryptoPaperExecutionConfig()
        self.risk_engine = risk_engine or RiskEngine()

    def execute(
        self,
        recommendations: RecommendationOutput,
        latest_quotes: dict[str, Any],
        as_of: datetime,
        ledger: CryptoPaperLedger | None = None,
        exit_events: list[CryptoPaperExitEvent] | None = None,
    ) -> CryptoPaperExecutionResult:
        active_ledger = ledger or CryptoPaperLedger(self.config)
        accepted_orders: list[CryptoPaperOrder] = []
        rejected_orders: list[CryptoPaperOrder] = []
        fills: list[CryptoPaperFill] = []
        warnings: list[str] = []
        applied_exit_events: list[CryptoPaperExitEvent] = []

        for index, item in enumerate(recommendations.recommendations, start=1):
            order = self._build_order(item, as_of, index)
            if order is None:
                continue
            validation_error = self._validate_item(item, latest_quotes)
            if validation_error:
                rejected_orders.append(self._reject(order, validation_error))
                continue

            price = self._reference_price(item, latest_quotes)
            notional = self._requested_notional(item)
            risk_result = self.risk_engine.evaluate(
                RiskCheckInput(
                    symbol=item.asset_id,
                    side=item.action,
                    quantity=None,
                    notional=notional,
                    price=price,
                    cash_available=active_ledger.cash,
                    fees_estimate=self._estimate_fee(notional),
                    expected_net_edge=float(item.expected_return_net_pct or item.expected_return_gross_pct or 0.0),
                    provider_healthy=True,
                    data_quality_score=1.0,
                    metadata={"paper_only": item.extensions.get("paper_only", True)},
                )
            )
            if not risk_result.approved:
                rejected_orders.append(self._reject(order, f"risk:{risk_result.rejected_reason}"))
                continue

            fill = self._build_fill(order, item, price, notional, as_of, index)
            if not active_ledger.can_afford(fill.gross_notional, fill.fee):
                rejected_orders.append(self._reject(order, "insufficient_cash"))
                continue

            active_ledger.apply_buy_fill(fill)
            accepted_orders.append(order)
            fills.append(fill)

        for offset, exit_event in enumerate(list(exit_events or []), start=1):
            order = self._build_exit_order(exit_event, as_of, len(accepted_orders) + len(rejected_orders) + offset)
            rejection_reason = self._validate_exit_event(exit_event, active_ledger)
            if rejection_reason:
                rejected_orders.append(self._reject(order, rejection_reason))
                continue
            fill = self._build_exit_fill(order, exit_event, as_of, len(fills) + offset)
            try:
                active_ledger.apply_sell_fill(fill)
            except ValueError as exc:
                rejected_orders.append(self._reject(order, str(exc)))
                continue
            accepted_orders.append(order)
            fills.append(fill)
            applied_exit_events.append(
                CryptoPaperExitEvent(
                    exit_id=exit_event.exit_id,
                    symbol=exit_event.symbol,
                    position_quantity_before=exit_event.position_quantity_before,
                    exit_quantity=exit_event.exit_quantity,
                    exit_reason=exit_event.exit_reason,
                    trigger_price=exit_event.trigger_price,
                    fill_price=fill.fill_price,
                    gross_notional=fill.gross_notional,
                    fee=fill.fee,
                    slippage=fill.slippage,
                    realized_pnl=((fill.fill_price - exit_event.metadata.get("avg_entry_price", 0.0)) * fill.quantity) - fill.fee,
                    exited_at=fill.filled_at,
                    source=exit_event.source,
                    metadata=dict(exit_event.metadata or {}),
                )
            )

        marks = {
            normalize_crypto_symbol(symbol): self._extract_price(quote)
            for symbol, quote in latest_quotes.items()
            if self._extract_price(quote) is not None
        }
        active_ledger.mark_to_market(marks, as_of)
        snapshot = active_ledger.snapshot(as_of, metadata={"quote_currency": self.config.quote_currency})
        return CryptoPaperExecutionResult(
            accepted_orders=accepted_orders,
            rejected_orders=rejected_orders,
            fills=fills,
            portfolio_snapshot=snapshot,
            warnings=warnings,
            exit_events=applied_exit_events,
            metadata={"quote_currency": self.config.quote_currency, "exit_events_count": len(applied_exit_events)},
        )

    def _build_order(self, item: Any, as_of: datetime, index: int) -> CryptoPaperOrder | None:
        asset_id = normalize_crypto_symbol(item.asset_id or item.ticker)
        if not asset_id:
            return None
        return CryptoPaperOrder(
            order_id=f"crypto-paper-order-{format_id_stamp(as_of)}-{index:04d}",
            symbol=asset_id,
            side=str(item.action or "").upper(),
            requested_notional=self._requested_notional(item),
            requested_quantity=None,
            reference_price=float(item.price_used or 0.0),
            status="PENDING",
            reason=None,
            created_at=as_of,
            metadata=dict(item.extensions or {}),
        )

    def _validate_item(self, item: Any, latest_quotes: dict[str, Any]) -> str | None:
        symbol = normalize_crypto_symbol(item.asset_id or item.ticker)
        if not is_crypto_symbol(symbol):
            return "non_crypto_symbol"
        if str(item.action or "").upper() != "BUY":
            return "unsupported_action"
        if bool(item.extensions.get("live_enabled")):
            return "live_disabled"
        if not bool(item.extensions.get("paper_only", True)):
            return "paper_only_required"
        price = self._reference_price(item, latest_quotes)
        if price is None or price <= 0:
            return "missing_price"
        notional = self._requested_notional(item)
        if notional < float(self.config.min_notional_per_order):
            return "below_min_notional"
        if notional > float(self.config.max_notional_per_order):
            return "above_max_notional"
        return None

    def _validate_exit_event(self, event: CryptoPaperExitEvent, ledger: CryptoPaperLedger) -> str | None:
        position = ledger.positions.get(normalize_crypto_symbol(event.symbol))
        if position is None or float(position.quantity) <= 0.0:
            return "position_not_found"
        if float(event.exit_quantity or 0.0) <= 0.0:
            return "invalid_exit_quantity"
        if float(event.exit_quantity) > float(position.quantity) + 1e-9:
            return "sell_qty_exceeds_position"
        return None

    def _requested_notional(self, item: Any) -> float:
        extension_notional = item.extensions.get("max_paper_notional")
        if extension_notional is not None:
            try:
                return float(extension_notional)
            except (TypeError, ValueError):
                pass
        for value in (item.usd_target_effective, item.usd_target):
            try:
                numeric = float(value or 0.0)
            except (TypeError, ValueError):
                numeric = 0.0
            if numeric > 0:
                return numeric
        return float(self.config.max_notional_per_order)

    def _reference_price(self, item: Any, latest_quotes: dict[str, Any]) -> float | None:
        symbol = normalize_crypto_symbol(item.asset_id or item.ticker)
        quote = latest_quotes.get(symbol) or latest_quotes.get(item.asset_id) or latest_quotes.get(item.ticker)
        if isinstance(quote, dict):
            if quote.get("ask") is not None:
                return float(quote["ask"])
            if quote.get("last_price") is not None:
                return float(quote["last_price"])
        if item.price_used is not None:
            try:
                return float(item.price_used)
            except (TypeError, ValueError):
                return None
        return None

    def _extract_price(self, quote: Any) -> float | None:
        if isinstance(quote, dict):
            for key in ("last_price", "ask", "bid"):
                if quote.get(key) is not None:
                    return float(quote[key])
        if isinstance(quote, (int, float)):
            return float(quote)
        return None

    def _estimate_fee(self, notional: float) -> float:
        return float(notional) * float(self.config.fee_bps) / 10000.0

    def _build_fill(self, order: CryptoPaperOrder, item: Any, reference_price: float, notional: float, as_of: datetime, index: int) -> CryptoPaperFill:
        slippage = float(reference_price) * float(self.config.slippage_bps) / 10000.0
        fill_price = float(reference_price) + slippage
        gross_notional = float(notional)
        fee = self._estimate_fee(gross_notional)
        quantity = gross_notional / fill_price if fill_price > 0 else 0.0
        return CryptoPaperFill(
            fill_id=f"crypto-paper-fill-{format_id_stamp(as_of)}-{index:04d}",
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            quantity=quantity,
            fill_price=fill_price,
            gross_notional=gross_notional,
            fee=fee,
            slippage=slippage,
            net_notional=gross_notional + fee,
            filled_at=as_of,
            metadata={
                "stop_loss": item.extensions.get("stop_loss"),
                "take_profit": item.extensions.get("take_profit"),
                "provider": item.extensions.get("provider"),
            },
        )

    def _build_exit_order(self, event: CryptoPaperExitEvent, as_of: datetime, index: int) -> CryptoPaperOrder:
        return CryptoPaperOrder(
            order_id=f"crypto-paper-exit-order-{format_id_stamp(as_of)}-{index:04d}",
            symbol=normalize_crypto_symbol(event.symbol),
            side="SELL",
            requested_notional=float(event.gross_notional or 0.0),
            requested_quantity=float(event.exit_quantity or 0.0),
            reference_price=float(event.trigger_price or 0.0),
            status="PENDING",
            reason=None,
            created_at=as_of,
            metadata={"exit_reason": event.exit_reason, "source": event.source, **dict(event.metadata or {})},
        )

    def _build_exit_fill(self, order: CryptoPaperOrder, event: CryptoPaperExitEvent, as_of: datetime, index: int) -> CryptoPaperFill:
        reference_price = float(event.trigger_price or order.reference_price or 0.0)
        slippage = float(reference_price) * float(self.config.slippage_bps) / 10000.0
        fill_price = float(reference_price) - slippage
        quantity = float(event.exit_quantity or 0.0)
        gross_notional = quantity * fill_price
        fee = self._estimate_fee(gross_notional)
        return CryptoPaperFill(
            fill_id=f"crypto-paper-exit-fill-{format_id_stamp(as_of)}-{index:04d}",
            order_id=order.order_id,
            symbol=order.symbol,
            side="SELL",
            quantity=quantity,
            fill_price=fill_price,
            gross_notional=gross_notional,
            fee=fee,
            slippage=slippage,
            net_notional=gross_notional - fee,
            filled_at=event.exited_at or as_of,
            metadata={"exit_reason": event.exit_reason, "source": event.source, **dict(event.metadata or {})},
        )

    def _reject(self, order: CryptoPaperOrder, reason: str) -> CryptoPaperOrder:
        return CryptoPaperOrder(
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            requested_notional=order.requested_notional,
            requested_quantity=order.requested_quantity,
            reference_price=order.reference_price,
            status="REJECTED",
            reason=reason,
            created_at=order.created_at,
            metadata=dict(order.metadata),
        )


def write_crypto_paper_execution_artifacts(
    run_id: str,
    result: CryptoPaperExecutionResult,
    base_path: str = "runs",
) -> dict[str, Path]:
    run_root = ensure_run_dir(run_id, base_path=base_path)
    target_dir = run_root / "artifacts" / "crypto_paper"
    target_dir.mkdir(parents=True, exist_ok=True)
    payloads = {
        "crypto_paper_orders.json": [order.to_dict() for order in result.accepted_orders + result.rejected_orders],
        "crypto_paper_fills.json": [fill.to_dict() for fill in result.fills],
        "crypto_paper_exit_events.json": [event.to_dict() for event in result.exit_events],
        "crypto_paper_positions.json": [position.to_dict() for position in result.portfolio_snapshot.positions],
        "crypto_paper_snapshot.json": result.portfolio_snapshot.to_dict(),
        "crypto_paper_execution_result.json": result.to_dict(),
    }
    written: dict[str, Path] = {}
    for filename, payload in payloads.items():
        path = target_dir / filename
        path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
        written[filename] = path
    return written


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def load_crypto_paper_ledger(
    run_id: str,
    base_path: str = "runs",
    config: CryptoPaperExecutionConfig | None = None,
) -> CryptoPaperLedger:
    active_config = config or CryptoPaperExecutionConfig()
    ledger = CryptoPaperLedger(active_config)
    root = Path(base_path) / run_id / "artifacts" / "crypto_paper"
    snapshot_path = root / "crypto_paper_snapshot.json"
    positions_path = root / "crypto_paper_positions.json"
    if snapshot_path.exists():
        try:
            snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            if isinstance(snapshot, dict):
                ledger.cash = float(snapshot.get("cash") or ledger.cash)
                ledger.fees_paid = float(snapshot.get("fees_paid") or 0.0)
                ledger.realized_pnl = float(snapshot.get("realized_pnl") or 0.0)
        except Exception:
            pass
    if positions_path.exists():
        try:
            payload = json.loads(positions_path.read_text(encoding="utf-8"))
        except Exception:
            payload = []
        if isinstance(payload, list):
            for item in payload:
                position = _position_from_payload(item)
                if position is not None and float(position.quantity) > 0.0:
                    ledger.positions[position.symbol] = position
    return ledger


def _position_from_payload(payload: Any) -> CryptoPaperPosition | None:
    if not isinstance(payload, dict):
        return None
    try:
        updated = payload.get("updated_at")
        updated_at = datetime.fromisoformat(str(updated).replace("Z", "+00:00")) if updated else None
        return CryptoPaperPosition(
            symbol=normalize_crypto_symbol(payload.get("symbol") or ""),
            quantity=float(payload.get("quantity") or 0.0),
            avg_entry_price=float(payload.get("avg_entry_price") or 0.0),
            realized_pnl=float(payload.get("realized_pnl") or 0.0),
            unrealized_pnl=float(payload.get("unrealized_pnl") or 0.0),
            last_price=float(payload["last_price"]) if payload.get("last_price") is not None else None,
            updated_at=updated_at,
            metadata=dict(payload.get("metadata") or {}),
        )
    except Exception:
        return None
