from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .crypto_paper_models import CryptoPaperPortfolioSnapshot, CryptoPaperPosition
from .crypto_paper_performance import CryptoPaperPerformanceSummary, compute_crypto_paper_performance


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
class CryptoPaperDailyCloseResult:
    as_of: datetime
    input_artifacts_found: list[str]
    positions_marked: list[CryptoPaperPosition]
    performance: CryptoPaperPerformanceSummary
    warnings: list[str] = field(default_factory=list)
    provider_health: dict[str, Any] = field(default_factory=dict)
    artifacts_written: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    paper_only: bool = True
    live_trading: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


def close_crypto_paper_day(
    *,
    artifacts_dir: str | Path,
    as_of: datetime,
    output_dir: str | Path | None = None,
    price_map: dict[str, Any] | None = None,
    provider: Any | None = None,
    provider_health: dict[str, Any] | None = None,
    starting_cash: float = 100.0,
) -> CryptoPaperDailyCloseResult:
    artifact_root = Path(artifacts_dir)
    target_dir = Path(output_dir) if output_dir is not None else artifact_root / "daily_close"
    warnings: list[str] = []
    if isinstance(provider_health, dict) and str(provider_health.get("status") or "").lower() == "unhealthy":
        warnings.append("Provider unhealthy during crypto paper daily close.")
    loaded = load_crypto_paper_artifacts(artifact_root, warnings)
    current_snapshot = _extract_snapshot(loaded)
    positions = _extract_positions(loaded, warnings)
    symbols = sorted({position.symbol for position in positions if position.symbol})
    marks, mark_warnings = _resolve_marks(symbols=symbols, positions=positions, price_map=price_map, provider=provider)
    warnings.extend(mark_warnings)
    marked_positions = _mark_positions(positions, marks, as_of, warnings)

    current_snapshot = _updated_snapshot(current_snapshot, marked_positions, starting_cash, as_of)
    accepted_orders_count, rejected_orders_count = _order_counts(loaded)
    fills_count = _fills_count(loaded)
    exit_events_count = _exit_events_count(loaded)
    performance = compute_crypto_paper_performance(
        as_of=as_of,
        positions=marked_positions,
        ending_cash=float(current_snapshot.cash if current_snapshot is not None else starting_cash),
        current_snapshot=current_snapshot,
        previous_snapshot=None,
        starting_cash=starting_cash,
        fills_count=fills_count,
        accepted_orders_count=accepted_orders_count,
        rejected_orders_count=rejected_orders_count,
        exit_events_count=exit_events_count,
        warnings=warnings,
        provider_health=dict(provider_health or {}),
        metadata={
            "source_artifacts": sorted(loaded["found"]),
            "paper_only": True,
            "live_trading": False,
            "exit_events_count": exit_events_count,
        },
    )
    result = CryptoPaperDailyCloseResult(
        as_of=as_of,
        input_artifacts_found=sorted(loaded["found"]),
        positions_marked=marked_positions,
        performance=performance,
        warnings=warnings,
        provider_health=dict(provider_health or {}),
        metadata={
            "source_artifacts": sorted(loaded["found"]),
            "artifacts_dir": str(artifact_root),
            "output_dir": str(target_dir),
        },
    )
    written = write_crypto_paper_daily_close_artifacts(target_dir, result)
    return CryptoPaperDailyCloseResult(
        as_of=result.as_of,
        input_artifacts_found=result.input_artifacts_found,
        positions_marked=result.positions_marked,
        performance=result.performance,
        warnings=result.warnings,
        provider_health=result.provider_health,
        artifacts_written={name: str(path) for name, path in written.items()},
        metadata=result.metadata,
        paper_only=result.paper_only,
        live_trading=result.live_trading,
    )


def load_crypto_paper_artifacts(artifact_root: str | Path, warnings: list[str] | None = None) -> dict[str, Any]:
    root = Path(artifact_root)
    warnings_list = warnings if warnings is not None else []
    optional_files = {"exit_events"}
    files = {
        "orders": root / "crypto_paper_orders.json",
        "fills": root / "crypto_paper_fills.json",
        "exit_events": root / "crypto_paper_exit_events.json",
        "positions": root / "crypto_paper_positions.json",
        "snapshot": root / "crypto_paper_snapshot.json",
        "execution_result": root / "crypto_paper_execution_result.json",
    }
    found: list[str] = []
    payloads: dict[str, Any] = {}
    for name, path in files.items():
        if not path.exists():
            if name not in optional_files:
                warnings_list.append(f"Missing artifact: {path.name}")
            payloads[name] = None
            continue
        found.append(path.name)
        try:
            text = path.read_text(encoding="utf-8").strip()
            if not text:
                warnings_list.append(f"Empty artifact: {path.name}")
                payloads[name] = None
                continue
            payloads[name] = json.loads(text)
        except Exception as exc:
            warnings_list.append(f"Malformed artifact {path.name}: {exc}")
            payloads[name] = None
    payloads["found"] = found
    return payloads


def write_crypto_paper_daily_close_artifacts(output_dir: str | Path, result: CryptoPaperDailyCloseResult) -> dict[str, Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    report = build_crypto_paper_daily_report(result)
    payloads: dict[str, Any] = {
        "crypto_paper_daily_close.json": result.to_dict(),
        "crypto_paper_performance_summary.json": result.performance.to_dict(),
        "crypto_paper_positions_marked.json": [position.to_dict() for position in result.positions_marked],
    }
    written: dict[str, Path] = {}
    for filename, payload in payloads.items():
        path = target / filename
        path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
        written[filename] = path
    report_path = target / "crypto_paper_daily_report.md"
    report_path.write_text(report, encoding="utf-8")
    written[report_path.name] = report_path
    return written


def build_crypto_paper_daily_report(result: CryptoPaperDailyCloseResult) -> str:
    performance = result.performance
    lines = [
        "# Crypto Paper Daily Close",
        "",
        "Paper-only simulated close. No live orders were placed.",
        "",
        "## Summary",
        f"- As of: {result.as_of.isoformat()}",
        f"- Starting equity: {performance.starting_equity:.6f}",
        f"- Ending equity: {performance.ending_equity:.6f}",
        f"- Total P&L: {performance.total_pnl:.6f}",
        f"- Total return %: {performance.total_return_pct * 100.0:.4f}",
        f"- Realized P&L: {performance.realized_pnl:.6f}",
        f"- Fees paid: {performance.fees_paid:.6f}",
        f"- Exit events: {performance.exit_events_count}",
        "",
        "## Positions",
    ]
    if not result.positions_marked:
        lines.append("- No open positions.")
    else:
        for position in result.positions_marked:
            mark = position.last_price if position.last_price is not None else position.avg_entry_price
            value = float(mark or 0.0) * float(position.quantity or 0.0)
            pnl_pct = (
                (float(position.unrealized_pnl or 0.0) / (float(position.avg_entry_price or 0.0) * float(position.quantity or 0.0)))
                if abs(float(position.avg_entry_price or 0.0) * float(position.quantity or 0.0)) > 1e-12
                else 0.0
            )
            lines.append(
                f"- {position.symbol}: qty={position.quantity:.8f} avg_entry={position.avg_entry_price:.6f} "
                f"last={float(mark or 0.0):.6f} value={value:.6f} "
                f"unrealized_pnl={float(position.unrealized_pnl or 0.0):.6f} "
                f"unrealized_pnl_pct={pnl_pct * 100.0:.4f}"
            )
    lines.extend(
        [
            "",
            "## Orders and Fills",
            f"- Accepted orders: {performance.accepted_orders_count}",
            f"- Rejected orders: {performance.rejected_orders_count}",
            f"- Fills: {performance.fills_count}",
            f"- Exit events: {performance.exit_events_count}",
            "",
            "## Warnings",
        ]
    )
    if not result.warnings:
        lines.append("- None.")
    else:
        for warning in result.warnings:
            lines.append(f"- {warning}")
    lines.extend(["", "## Notes", "- Paper-only.", "- No live orders placed."])
    return "\n".join(lines) + "\n"


def _extract_positions(loaded: dict[str, Any], warnings: list[str]) -> list[CryptoPaperPosition]:
    payload = loaded.get("positions")
    if isinstance(payload, list):
        positions = [_position_from_payload(item) for item in payload if isinstance(item, dict)]
        return [position for position in positions if position is not None]

    execution_payload = loaded.get("execution_result")
    if isinstance(execution_payload, dict):
        snapshot = execution_payload.get("portfolio_snapshot")
        if isinstance(snapshot, dict) and isinstance(snapshot.get("positions"), list):
            positions = [_position_from_payload(item) for item in snapshot["positions"] if isinstance(item, dict)]
            return [position for position in positions if position is not None]

    warnings.append("No crypto positions artifact available; daily close used empty position set.")
    return []


def _extract_snapshot(loaded: dict[str, Any]) -> CryptoPaperPortfolioSnapshot | None:
    payload = loaded.get("snapshot")
    if isinstance(payload, dict):
        snapshot = _snapshot_from_payload(payload)
        if snapshot is not None:
            return snapshot

    execution_payload = loaded.get("execution_result")
    if isinstance(execution_payload, dict) and isinstance(execution_payload.get("portfolio_snapshot"), dict):
        return _snapshot_from_payload(execution_payload["portfolio_snapshot"])
    return None


def _resolve_marks(
    *,
    symbols: list[str],
    positions: list[CryptoPaperPosition],
    price_map: dict[str, Any] | None,
    provider: Any | None,
) -> tuple[dict[str, float], list[str]]:
    warnings: list[str] = []
    marks: dict[str, float] = {}
    explicit_prices = dict(price_map or {})
    for symbol in symbols:
        resolved = _extract_mark(explicit_prices.get(symbol))
        if resolved is not None:
            marks[symbol] = resolved
            continue
        if provider is None:
            continue
        try:
            quote = provider.get_latest_quote(symbol)
        except Exception as exc:
            warnings.append(f"Provider mark failed for {symbol}: {exc}")
            continue
        resolved = _extract_mark(quote, prefer_bid=True)
        if resolved is not None:
            marks[symbol] = resolved
    return marks, warnings


def _mark_positions(
    positions: list[CryptoPaperPosition],
    marks: dict[str, float],
    as_of: datetime,
    warnings: list[str],
) -> list[CryptoPaperPosition]:
    marked: list[CryptoPaperPosition] = []
    for position in positions:
        mark = marks.get(position.symbol)
        if mark is None:
            if position.last_price is not None:
                warnings.append(f"Missing latest price for {position.symbol}; used last known price.")
                mark = float(position.last_price)
            else:
                warnings.append(f"Missing latest price for {position.symbol}; used avg entry price.")
                mark = float(position.avg_entry_price)
        unrealized = (float(mark) - float(position.avg_entry_price)) * float(position.quantity)
        marked.append(
            CryptoPaperPosition(
                symbol=position.symbol,
                quantity=float(position.quantity),
                avg_entry_price=float(position.avg_entry_price),
                realized_pnl=float(position.realized_pnl or 0.0),
                unrealized_pnl=float(unrealized),
                last_price=float(mark),
                updated_at=as_of,
                metadata=dict(position.metadata or {}),
            )
        )
    return marked


def _updated_snapshot(
    current_snapshot: CryptoPaperPortfolioSnapshot | None,
    positions: list[CryptoPaperPosition],
    starting_cash: float,
    as_of: datetime,
) -> CryptoPaperPortfolioSnapshot:
    cash = float(current_snapshot.cash) if current_snapshot is not None else float(starting_cash)
    fees_paid = float(current_snapshot.fees_paid) if current_snapshot is not None else 0.0
    realized_pnl = float(current_snapshot.realized_pnl) if current_snapshot is not None else 0.0
    positions_value = sum((float(position.last_price or position.avg_entry_price)) * float(position.quantity) for position in positions)
    unrealized = sum(float(position.unrealized_pnl or 0.0) for position in positions)
    metadata = dict(current_snapshot.metadata) if current_snapshot is not None else {"source": "crypto_paper_daily_close"}
    return CryptoPaperPortfolioSnapshot(
        as_of=as_of,
        cash=cash,
        equity=cash + positions_value,
        positions_value=positions_value,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized,
        fees_paid=fees_paid,
        positions=positions,
        metadata=metadata,
    )


def _order_counts(loaded: dict[str, Any]) -> tuple[int, int]:
    execution_payload = loaded.get("execution_result")
    if isinstance(execution_payload, dict):
        accepted = execution_payload.get("accepted_orders")
        rejected = execution_payload.get("rejected_orders")
        if isinstance(accepted, list) and isinstance(rejected, list):
            return len(accepted), len(rejected)

    orders = loaded.get("orders")
    if not isinstance(orders, list):
        return 0, 0
    accepted = 0
    rejected = 0
    for order in orders:
        if not isinstance(order, dict):
            continue
        if str(order.get("status") or "").upper() == "REJECTED":
            rejected += 1
        else:
            accepted += 1
    return accepted, rejected


def _fills_count(loaded: dict[str, Any]) -> int:
    execution_payload = loaded.get("execution_result")
    if isinstance(execution_payload, dict) and isinstance(execution_payload.get("fills"), list):
        return len(execution_payload["fills"])
    fills = loaded.get("fills")
    return len(fills) if isinstance(fills, list) else 0


def _exit_events_count(loaded: dict[str, Any]) -> int:
    execution_payload = loaded.get("execution_result")
    if isinstance(execution_payload, dict) and isinstance(execution_payload.get("exit_events"), list):
        return len(execution_payload["exit_events"])
    events = loaded.get("exit_events")
    return len(events) if isinstance(events, list) else 0


def _position_from_payload(payload: dict[str, Any]) -> CryptoPaperPosition | None:
    try:
        return CryptoPaperPosition(
            symbol=str(payload.get("symbol") or "").strip().upper(),
            quantity=float(payload.get("quantity") or 0.0),
            avg_entry_price=float(payload.get("avg_entry_price") or 0.0),
            realized_pnl=float(payload.get("realized_pnl") or 0.0),
            unrealized_pnl=float(payload.get("unrealized_pnl") or 0.0),
            last_price=float(payload["last_price"]) if payload.get("last_price") is not None else None,
            updated_at=_parse_datetime(payload.get("updated_at")),
            metadata=dict(payload.get("metadata") or {}),
        )
    except Exception:
        return None


def _snapshot_from_payload(payload: dict[str, Any]) -> CryptoPaperPortfolioSnapshot | None:
    try:
        positions = [_position_from_payload(item) for item in payload.get("positions", []) if isinstance(item, dict)]
        return CryptoPaperPortfolioSnapshot(
            as_of=_parse_datetime(payload.get("as_of")) or datetime.utcnow(),
            cash=float(payload.get("cash") or 0.0),
            equity=float(payload.get("equity") or 0.0),
            positions_value=float(payload.get("positions_value") or 0.0),
            realized_pnl=float(payload.get("realized_pnl") or 0.0),
            unrealized_pnl=float(payload.get("unrealized_pnl") or 0.0),
            fees_paid=float(payload.get("fees_paid") or 0.0),
            positions=[position for position in positions if position is not None],
            metadata=dict(payload.get("metadata") or {}),
        )
    except Exception:
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _extract_mark(value: Any, prefer_bid: bool = False) -> float | None:
    if isinstance(value, dict):
        keys = ("bid", "last_price", "ask") if prefer_bid else ("last_price", "bid", "ask")
        for key in keys:
            if value.get(key) is not None:
                return float(value[key])
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None
