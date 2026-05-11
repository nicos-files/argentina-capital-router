from __future__ import annotations

import json
import math
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any


EPSILON = 1e-12


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
class CryptoPaperTrade:
    trade_id: str
    symbol: str
    entry_fill_id: str | None
    exit_fill_id: str | None
    exit_event_id: str | None
    entry_time: str | None
    exit_time: str | None
    side: str
    quantity: float
    entry_price: float | None
    exit_price: float | None
    gross_entry_notional: float
    gross_exit_notional: float | None
    entry_fee: float
    exit_fee: float
    total_fees: float
    entry_slippage: float
    exit_slippage: float
    total_slippage: float
    gross_pnl: float | None
    net_pnl: float | None
    return_pct: float | None
    holding_seconds: float | None
    exit_reason: str | None
    result: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True)
class CryptoPaperStrategyMetrics:
    closed_trades_count: int
    open_trades_count: int
    winning_trades_count: int
    losing_trades_count: int
    flat_trades_count: int
    win_rate: float | None
    loss_rate: float | None
    average_win: float | None
    average_loss: float | None
    average_trade_pnl: float | None
    median_trade_pnl: float | None
    best_trade: dict[str, Any] | None
    worst_trade: dict[str, Any] | None
    gross_profit: float
    gross_loss: float
    net_profit: float
    profit_factor: float | None
    expectancy: float | None
    average_return_pct: float | None
    average_holding_seconds: float | None
    total_fees: float
    total_slippage: float
    fee_drag_pct_of_gross_pnl: float | None
    slippage_drag_pct_of_gross_pnl: float | None
    stop_loss_count: int
    take_profit_count: int
    manual_sell_count: int
    stop_loss_rate: float | None
    take_profit_rate: float | None
    average_win_loss_ratio: float | None
    largest_win: float | None
    largest_loss: float | None
    consecutive_wins_max: int
    consecutive_losses_max: int
    symbols_traded: list[str]
    per_symbol_metrics: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    paper_only: bool = True
    live_trading: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


def evaluate_crypto_paper_strategy(
    artifacts_dir: str | Path,
    output_dir: str | Path | None = None,
) -> tuple[list[CryptoPaperTrade], list[CryptoPaperTrade], CryptoPaperStrategyMetrics, dict[str, Any], dict[str, Any], dict[str, Path], list[str]]:
    artifact_root = Path(artifacts_dir)
    target_dir = Path(output_dir) if output_dir is not None else artifact_root / "evaluation"
    payloads, warnings = load_crypto_paper_evaluation_inputs(artifact_root)
    closed_trades, open_trades, pairing_warnings = build_crypto_paper_trade_log(payloads)
    all_warnings = list(warnings) + list(pairing_warnings)
    metrics = compute_crypto_paper_strategy_metrics(closed_trades, open_trades, warnings=all_warnings)
    exit_breakdown = build_exit_reason_breakdown(closed_trades)
    fee_report = build_fee_slippage_report(closed_trades, metrics)
    written = write_crypto_paper_evaluation_artifacts(
        target_dir,
        closed_trades=closed_trades,
        open_trades=open_trades,
        metrics=metrics,
        exit_breakdown=exit_breakdown,
        fee_report=fee_report,
    )
    return closed_trades, open_trades, metrics, exit_breakdown, fee_report, written, all_warnings


def load_crypto_paper_evaluation_inputs(artifact_root: str | Path) -> tuple[dict[str, Any], list[str]]:
    root = Path(artifact_root)
    warnings: list[str] = []
    files = {
        "fills": root / "crypto_paper_fills.json",
        "exit_events": root / "crypto_paper_exit_events.json",
        "orders": root / "crypto_paper_orders.json",
        "snapshot": root / "crypto_paper_snapshot.json",
        "history": root / "history" / "crypto_paper_performance_history.json",
        "equity_curve": root / "history" / "crypto_paper_equity_curve.json",
    }
    payloads: dict[str, Any] = {}
    for name, path in files.items():
        if not path.exists():
            warnings.append(f"Missing artifact: {path.name}")
            payloads[name] = None
            continue
        try:
            text = path.read_text(encoding="utf-8").strip()
            payloads[name] = json.loads(text) if text else None
        except Exception as exc:
            warnings.append(f"Malformed artifact {path.name}: {exc}")
            payloads[name] = None
    return payloads, warnings


def build_crypto_paper_trade_log(payloads: dict[str, Any]) -> tuple[list[CryptoPaperTrade], list[CryptoPaperTrade], list[str]]:
    warnings: list[str] = []
    fills = payloads.get("fills")
    snapshot = payloads.get("snapshot")
    exit_events = payloads.get("exit_events")
    snapshot_positions_payload = _snapshot_positions(snapshot if isinstance(snapshot, dict) else {})
    fills_is_empty = (not isinstance(fills, list)) or (isinstance(fills, list) and len(fills) == 0)
    if fills_is_empty and snapshot_positions_payload:
        warnings.append(
            "ledger_history_inconsistency: positions exist but no fills found in cumulative log."
        )
    if not isinstance(fills, list):
        warnings.append("No fills available; strategy trade log is limited.")
        return [], [], warnings

    exit_lookup = _build_exit_lookup(exit_events if isinstance(exit_events, list) else [])
    snapshot_positions = _snapshot_positions(snapshot if isinstance(snapshot, dict) else {})
    lots_by_symbol: dict[str, deque[dict[str, Any]]] = defaultdict(deque)
    closed_trades: list[CryptoPaperTrade] = []

    ordered_fills = sorted(
        [fill for fill in fills if isinstance(fill, dict)],
        key=lambda fill: _parse_datetime(fill.get("filled_at")) or datetime.min,
    )
    trade_counter = 0
    for fill in ordered_fills:
        symbol = str(fill.get("symbol") or "").strip().upper()
        side = str(fill.get("side") or "").strip().upper()
        if not symbol or side not in {"BUY", "SELL"}:
            continue
        if side == "BUY":
            lots_by_symbol[symbol].append(_buy_lot(fill))
            continue

        remaining_qty = float(fill.get("quantity") or 0.0)
        if remaining_qty <= EPSILON:
            continue
        queue = lots_by_symbol[symbol]
        if not queue:
            warnings.append(f"Unmatched SELL fill for {symbol}: {fill.get('fill_id')}")
            continue
        while remaining_qty > EPSILON and queue:
            lot = queue[0]
            matched_qty = min(remaining_qty, float(lot["remaining_qty"]))
            trade_counter += 1
            closed_trades.append(
                _closed_trade_from_match(
                    trade_index=trade_counter,
                    symbol=symbol,
                    buy_lot=lot,
                    sell_fill=fill,
                    matched_qty=matched_qty,
                    exit_event=_match_exit_event(exit_lookup, fill, symbol),
                )
            )
            lot["remaining_qty"] -= matched_qty
            remaining_qty -= matched_qty
            if lot["remaining_qty"] <= EPSILON:
                queue.popleft()
        if remaining_qty > EPSILON:
            warnings.append(f"SELL fill exceeded open quantity for {symbol}: {fill.get('fill_id')}")

    open_trades: list[CryptoPaperTrade] = []
    for symbol, queue in lots_by_symbol.items():
        for lot in queue:
            if float(lot["remaining_qty"]) <= EPSILON:
                continue
            trade_counter += 1
            open_trades.append(
                _open_trade_from_lot(
                    trade_index=trade_counter,
                    symbol=symbol,
                    lot=lot,
                    position_mark=snapshot_positions.get(symbol),
                )
            )
    open_trades.sort(key=lambda trade: (trade.entry_time or "", trade.symbol, trade.trade_id))
    return closed_trades, open_trades, warnings


def compute_crypto_paper_strategy_metrics(
    closed_trades: list[CryptoPaperTrade],
    open_trades: list[CryptoPaperTrade],
    warnings: list[str] | None = None,
) -> CryptoPaperStrategyMetrics:
    all_warnings = list(warnings or [])
    if len(closed_trades) < 30:
        all_warnings.append("Small sample size: fewer than 30 closed trades.")
    if not closed_trades:
        all_warnings.append("No closed trades available; strategy metrics are limited.")
    if open_trades:
        all_warnings.append("Open trades are excluded from closed-trade expectancy.")
    all_warnings.append("Paper-only results; no real execution occurred.")
    all_warnings.append("Fees and slippage are simulated.")

    wins = [trade for trade in closed_trades if trade.result == "WIN"]
    losses = [trade for trade in closed_trades if trade.result == "LOSS"]
    flats = [trade for trade in closed_trades if trade.result == "FLAT"]
    pnl_values = [float(trade.net_pnl or 0.0) for trade in closed_trades]
    gross_values = [float(trade.gross_pnl or 0.0) for trade in closed_trades]
    total_fees = sum(float(trade.total_fees or 0.0) for trade in closed_trades)
    total_slippage = sum(float(trade.total_slippage or 0.0) for trade in closed_trades)
    gross_profit = sum(float(trade.net_pnl or 0.0) for trade in wins)
    gross_loss = abs(sum(float(trade.net_pnl or 0.0) for trade in losses))
    net_profit = sum(pnl_values)
    average_win = _average([float(trade.net_pnl or 0.0) for trade in wins])
    average_loss = _average([float(trade.net_pnl or 0.0) for trade in losses])
    win_rate = (len(wins) / len(closed_trades)) if closed_trades else None
    loss_rate = (len(losses) / len(closed_trades)) if closed_trades else None
    expectancy = None
    if win_rate is not None and loss_rate is not None:
        expectancy = (win_rate * float(average_win or 0.0)) - (loss_rate * abs(float(average_loss or 0.0)))
    gross_pnl_sum = abs(sum(gross_values))
    profit_factor = (gross_profit / gross_loss) if gross_loss > EPSILON else None
    per_symbol = build_per_symbol_metrics(closed_trades, open_trades)
    return CryptoPaperStrategyMetrics(
        closed_trades_count=len(closed_trades),
        open_trades_count=len(open_trades),
        winning_trades_count=len(wins),
        losing_trades_count=len(losses),
        flat_trades_count=len(flats),
        win_rate=win_rate,
        loss_rate=loss_rate,
        average_win=average_win,
        average_loss=average_loss,
        average_trade_pnl=_average(pnl_values),
        median_trade_pnl=(median(pnl_values) if pnl_values else None),
        best_trade=(_trade_brief(max(closed_trades, key=lambda trade: float(trade.net_pnl or 0.0))) if closed_trades else None),
        worst_trade=(_trade_brief(min(closed_trades, key=lambda trade: float(trade.net_pnl or 0.0))) if closed_trades else None),
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        net_profit=net_profit,
        profit_factor=profit_factor,
        expectancy=expectancy,
        average_return_pct=_average([float(trade.return_pct or 0.0) for trade in closed_trades]) if closed_trades else None,
        average_holding_seconds=_average([float(trade.holding_seconds or 0.0) for trade in closed_trades]) if closed_trades else None,
        total_fees=total_fees,
        total_slippage=total_slippage,
        fee_drag_pct_of_gross_pnl=((total_fees / gross_pnl_sum) * 100.0) if gross_pnl_sum > EPSILON else None,
        slippage_drag_pct_of_gross_pnl=((total_slippage / gross_pnl_sum) * 100.0) if gross_pnl_sum > EPSILON else None,
        stop_loss_count=sum(1 for trade in closed_trades if trade.exit_reason == "STOP_LOSS"),
        take_profit_count=sum(1 for trade in closed_trades if trade.exit_reason == "TAKE_PROFIT"),
        manual_sell_count=sum(1 for trade in closed_trades if trade.exit_reason == "MANUAL_SELL"),
        stop_loss_rate=(sum(1 for trade in closed_trades if trade.exit_reason == "STOP_LOSS") / len(closed_trades)) if closed_trades else None,
        take_profit_rate=(sum(1 for trade in closed_trades if trade.exit_reason == "TAKE_PROFIT") / len(closed_trades)) if closed_trades else None,
        average_win_loss_ratio=((float(average_win) / abs(float(average_loss))) if average_win is not None and average_loss not in (None, 0.0) else None),
        largest_win=max([float(trade.net_pnl or 0.0) for trade in wins], default=None),
        largest_loss=min([float(trade.net_pnl or 0.0) for trade in losses], default=None),
        consecutive_wins_max=_max_streak(closed_trades, "WIN"),
        consecutive_losses_max=_max_streak(closed_trades, "LOSS"),
        symbols_traded=sorted({trade.symbol for trade in closed_trades + open_trades}),
        per_symbol_metrics=per_symbol,
        warnings=_dedupe(all_warnings),
        metadata={"paper_only": True, "live_trading": False},
    )


def build_exit_reason_breakdown(closed_trades: list[CryptoPaperTrade]) -> dict[str, Any]:
    reasons = ["STOP_LOSS", "TAKE_PROFIT", "MANUAL_SELL", "UNKNOWN"]
    total = len(closed_trades)
    breakdown: dict[str, Any] = {}
    for reason in reasons:
        trades = [trade for trade in closed_trades if (trade.exit_reason or "UNKNOWN") == reason]
        wins = [trade for trade in trades if trade.result == "WIN"]
        breakdown[reason] = {
            "count": len(trades),
            "share_pct": ((len(trades) / total) * 100.0) if total else 0.0,
            "total_net_pnl": sum(float(trade.net_pnl or 0.0) for trade in trades),
            "average_net_pnl": _average([float(trade.net_pnl or 0.0) for trade in trades]),
            "average_holding_seconds": _average([float(trade.holding_seconds or 0.0) for trade in trades]),
            "win_rate": ((len(wins) / len(trades)) if trades else None),
        }
    return breakdown


def build_fee_slippage_report(closed_trades: list[CryptoPaperTrade], metrics: CryptoPaperStrategyMetrics) -> dict[str, Any]:
    per_symbol_fees: dict[str, float] = defaultdict(float)
    entry_fees = 0.0
    exit_fees = 0.0
    entry_slippage = 0.0
    exit_slippage = 0.0
    for trade in closed_trades:
        per_symbol_fees[trade.symbol] += float(trade.total_fees or 0.0)
        entry_fees += float(trade.entry_fee or 0.0)
        exit_fees += float(trade.exit_fee or 0.0)
        entry_slippage += float(trade.entry_slippage or 0.0)
        exit_slippage += float(trade.exit_slippage or 0.0)
    gross_pnl_sum = abs(sum(float(trade.gross_pnl or 0.0) for trade in closed_trades))
    return {
        "total_entry_fees": entry_fees,
        "total_exit_fees": exit_fees,
        "total_fees": metrics.total_fees,
        "total_entry_slippage": entry_slippage,
        "total_exit_slippage": exit_slippage,
        "total_slippage": metrics.total_slippage,
        "average_fee_per_trade": _average([float(trade.total_fees or 0.0) for trade in closed_trades]),
        "average_slippage_per_trade": _average([float(trade.total_slippage or 0.0) for trade in closed_trades]),
        "fee_drag_pct_of_net_profit": ((metrics.total_fees / abs(metrics.net_profit)) * 100.0) if abs(metrics.net_profit) > EPSILON else None,
        "fee_drag_pct_of_gross_pnl": ((metrics.total_fees / gross_pnl_sum) * 100.0) if gross_pnl_sum > EPSILON else None,
        "symbols_with_highest_fee_drag": [
            {"symbol": symbol, "total_fees": fee}
            for symbol, fee in sorted(per_symbol_fees.items(), key=lambda item: item[1], reverse=True)[:5]
        ],
        "warnings": ["Fees and slippage are simulated."],
        "paper_only": True,
        "live_trading": False,
    }


def write_crypto_paper_evaluation_artifacts(
    output_dir: str | Path,
    *,
    closed_trades: list[CryptoPaperTrade],
    open_trades: list[CryptoPaperTrade],
    metrics: CryptoPaperStrategyMetrics,
    exit_breakdown: dict[str, Any],
    fee_report: dict[str, Any],
) -> dict[str, Path]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    trade_log = {
        "closed_trades": [trade.to_dict() for trade in closed_trades],
        "open_trades": [trade.to_dict() for trade in open_trades],
        "paper_only": True,
        "live_trading": False,
    }
    payloads: dict[str, Any] = {
        "crypto_paper_trade_log.json": trade_log,
        "crypto_paper_strategy_metrics.json": metrics.to_dict(),
        "crypto_paper_exit_reason_breakdown.json": exit_breakdown,
        "crypto_paper_fee_slippage_report.json": fee_report,
    }
    written: dict[str, Path] = {}
    for filename, payload in payloads.items():
        path = root / filename
        path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
        written[filename] = path
    report_path = root / "crypto_paper_strategy_evaluation_report.md"
    report_path.write_text(build_crypto_paper_strategy_evaluation_report(closed_trades, open_trades, metrics, exit_breakdown, fee_report), encoding="utf-8")
    written[report_path.name] = report_path
    return written


def build_crypto_paper_strategy_evaluation_report(
    closed_trades: list[CryptoPaperTrade],
    open_trades: list[CryptoPaperTrade],
    metrics: CryptoPaperStrategyMetrics,
    exit_breakdown: dict[str, Any],
    fee_report: dict[str, Any],
) -> str:
    lines = [
        "# Crypto Paper Strategy Evaluation",
        "",
        "Paper-only evaluation. Metrics are based on simulated fills, fees, and slippage.",
        "",
        "## Executive Summary",
        f"- Closed trades: {metrics.closed_trades_count}",
        f"- Open trades: {metrics.open_trades_count}",
        f"- Net profit: {metrics.net_profit:.6f}",
        f"- Win rate: {((metrics.win_rate or 0.0) * 100.0):.4f}",
        f"- Profit factor: {metrics.profit_factor if metrics.profit_factor is not None else 'n/a'}",
        f"- Expectancy: {metrics.expectancy if metrics.expectancy is not None else 'n/a'}",
        "",
        "## Trade Quality",
        f"- Average win: {metrics.average_win if metrics.average_win is not None else 'n/a'}",
        f"- Average loss: {metrics.average_loss if metrics.average_loss is not None else 'n/a'}",
        f"- Average win/loss ratio: {metrics.average_win_loss_ratio if metrics.average_win_loss_ratio is not None else 'n/a'}",
        f"- Best trade: {metrics.best_trade}",
        f"- Worst trade: {metrics.worst_trade}",
        f"- Consecutive wins max: {metrics.consecutive_wins_max}",
        f"- Consecutive losses max: {metrics.consecutive_losses_max}",
        "",
        "## Exit Breakdown",
    ]
    for reason in ("STOP_LOSS", "TAKE_PROFIT", "MANUAL_SELL", "UNKNOWN"):
        payload = exit_breakdown.get(reason) or {}
        lines.append(f"- {reason}: count={payload.get('count', 0)} total_net_pnl={payload.get('total_net_pnl', 0.0)}")
    lines.extend(
        [
            "",
            "## Fees and Slippage",
            f"- Total fees: {fee_report.get('total_fees', 0.0):.6f}",
            f"- Total slippage: {fee_report.get('total_slippage', 0.0):.6f}",
            f"- Fee drag % of gross P&L: {fee_report.get('fee_drag_pct_of_gross_pnl')}",
            "",
            "## Per-Symbol Results",
            "| Symbol | Trades | Win rate | Net P&L | Expectancy | Fees | Stop-loss count | Take-profit count |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for symbol, payload in sorted(metrics.per_symbol_metrics.items()):
        lines.append(
            f"| {symbol} | {payload['closed_trades_count']} | {((payload.get('win_rate') or 0.0) * 100.0):.4f} | "
            f"{payload['net_profit']:.6f} | {payload.get('expectancy')} | {payload['total_fees']:.6f} | "
            f"{payload['stop_loss_count']} | {payload['take_profit_count']} |"
        )
    lines.extend(["", "## Open Trades"])
    if not open_trades:
        lines.append("- None.")
    else:
        for trade in open_trades:
            lines.append(
                f"- {trade.symbol}: qty={trade.quantity:.8f} entry_price={trade.entry_price} entry_time={trade.entry_time} "
                f"unrealized={trade.metadata.get('unrealized_pnl')}"
            )
    lines.extend(["", "## Warnings"])
    for warning in metrics.warnings:
        lines.append(f"- {warning}")
    lines.extend(
        [
            "",
            "## Notes",
            "- Paper-only.",
            "- No live orders placed.",
            "- No broker integration.",
            "- Metrics are based on simulated fills, fees, and slippage.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_per_symbol_metrics(closed_trades: list[CryptoPaperTrade], open_trades: list[CryptoPaperTrade]) -> dict[str, Any]:
    symbols = sorted({trade.symbol for trade in closed_trades + open_trades})
    result: dict[str, Any] = {}
    for symbol in symbols:
        closed = [trade for trade in closed_trades if trade.symbol == symbol]
        open_symbol = [trade for trade in open_trades if trade.symbol == symbol]
        wins = [trade for trade in closed if trade.result == "WIN"]
        losses = [trade for trade in closed if trade.result == "LOSS"]
        average_loss = _average([float(trade.net_pnl or 0.0) for trade in losses])
        average_win = _average([float(trade.net_pnl or 0.0) for trade in wins])
        win_rate = (len(wins) / len(closed)) if closed else None
        loss_rate = (len(losses) / len(closed)) if closed else None
        expectancy = None
        if win_rate is not None and loss_rate is not None:
            expectancy = (win_rate * float(average_win or 0.0)) - (loss_rate * abs(float(average_loss or 0.0)))
        result[symbol] = {
            "closed_trades_count": len(closed),
            "open_trades_count": len(open_symbol),
            "win_rate": win_rate,
            "net_profit": sum(float(trade.net_pnl or 0.0) for trade in closed),
            "average_trade_pnl": _average([float(trade.net_pnl or 0.0) for trade in closed]),
            "best_trade": _trade_brief(max(closed, key=lambda trade: float(trade.net_pnl or 0.0))) if closed else None,
            "worst_trade": _trade_brief(min(closed, key=lambda trade: float(trade.net_pnl or 0.0))) if closed else None,
            "total_fees": sum(float(trade.total_fees or 0.0) for trade in closed),
            "stop_loss_count": sum(1 for trade in closed if trade.exit_reason == "STOP_LOSS"),
            "take_profit_count": sum(1 for trade in closed if trade.exit_reason == "TAKE_PROFIT"),
            "average_holding_seconds": _average([float(trade.holding_seconds or 0.0) for trade in closed]),
            "expectancy": expectancy,
        }
    return result


def _build_exit_lookup(exit_events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    lookup: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in exit_events:
        symbol = str(event.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        lookup[symbol].append(event)
    for symbol in lookup:
        lookup[symbol].sort(key=lambda item: _parse_datetime(item.get("exited_at")) or datetime.min)
    return lookup


def _snapshot_positions(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    positions = snapshot.get("positions") if isinstance(snapshot, dict) else None
    if not isinstance(positions, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for position in positions:
        if not isinstance(position, dict):
            continue
        symbol = str(position.get("symbol") or "").strip().upper()
        if symbol:
            result[symbol] = position
    return result


def _buy_lot(fill: dict[str, Any]) -> dict[str, Any]:
    quantity = float(fill.get("quantity") or 0.0)
    gross_notional = float(fill.get("gross_notional") or 0.0)
    return {
        "fill_id": fill.get("fill_id"),
        "entry_time": fill.get("filled_at"),
        "quantity": quantity,
        "remaining_qty": quantity,
        "fill_price": float(fill.get("fill_price") or 0.0),
        "gross_notional": gross_notional,
        "fee": float(fill.get("fee") or 0.0),
        "slippage": abs(float(fill.get("slippage") or 0.0)) * quantity,
        "metadata": dict(fill.get("metadata") or {}),
    }


def _closed_trade_from_match(
    *,
    trade_index: int,
    symbol: str,
    buy_lot: dict[str, Any],
    sell_fill: dict[str, Any],
    matched_qty: float,
    exit_event: dict[str, Any] | None,
) -> CryptoPaperTrade:
    buy_qty = float(buy_lot["quantity"] or 0.0)
    sell_qty = float(sell_fill.get("quantity") or 0.0)
    entry_fee = _prorate(float(buy_lot["fee"] or 0.0), matched_qty, buy_qty)
    exit_fee = _prorate(float(sell_fill.get("fee") or 0.0), matched_qty, sell_qty)
    entry_slippage = _prorate(float(buy_lot["slippage"] or 0.0), matched_qty, buy_qty)
    exit_slippage = _prorate(abs(float(sell_fill.get("slippage") or 0.0)) * sell_qty, matched_qty, sell_qty)
    entry_price = float(buy_lot["fill_price"] or 0.0)
    exit_price = float(sell_fill.get("fill_price") or 0.0)
    gross_entry = entry_price * matched_qty
    gross_exit = exit_price * matched_qty
    gross_pnl = gross_exit - gross_entry
    net_pnl = gross_pnl - entry_fee - exit_fee
    result = "FLAT"
    if net_pnl > EPSILON:
        result = "WIN"
    elif net_pnl < -EPSILON:
        result = "LOSS"
    entry_time = _parse_datetime(buy_lot.get("entry_time"))
    exit_time = _parse_datetime(sell_fill.get("filled_at"))
    holding_seconds = ((exit_time - entry_time).total_seconds() if entry_time and exit_time else None)
    exit_reason = (
        sell_fill.get("metadata", {}).get("exit_reason")
        if isinstance(sell_fill.get("metadata"), dict)
        else None
    ) or (exit_event.get("exit_reason") if exit_event else None) or "UNKNOWN"
    return_pct = ((net_pnl / gross_entry) * 100.0) if abs(gross_entry) > EPSILON else None
    return CryptoPaperTrade(
        trade_id=f"crypto-trade-{trade_index:04d}",
        symbol=symbol,
        entry_fill_id=str(buy_lot.get("fill_id") or ""),
        exit_fill_id=str(sell_fill.get("fill_id") or ""),
        exit_event_id=str(exit_event.get("exit_id") or "") if exit_event else None,
        entry_time=entry_time.isoformat() if entry_time else buy_lot.get("entry_time"),
        exit_time=exit_time.isoformat() if exit_time else sell_fill.get("filled_at"),
        side="LONG",
        quantity=matched_qty,
        entry_price=entry_price,
        exit_price=exit_price,
        gross_entry_notional=gross_entry,
        gross_exit_notional=gross_exit,
        entry_fee=entry_fee,
        exit_fee=exit_fee,
        total_fees=entry_fee + exit_fee,
        entry_slippage=entry_slippage,
        exit_slippage=exit_slippage,
        total_slippage=entry_slippage + exit_slippage,
        gross_pnl=gross_pnl,
        net_pnl=net_pnl,
        return_pct=return_pct,
        holding_seconds=holding_seconds,
        exit_reason=exit_reason,
        result=result,
        metadata={
            "entry_metadata": dict(buy_lot.get("metadata") or {}),
            "exit_metadata": dict(sell_fill.get("metadata") or {}),
        },
    )


def _open_trade_from_lot(
    *,
    trade_index: int,
    symbol: str,
    lot: dict[str, Any],
    position_mark: dict[str, Any] | None,
) -> CryptoPaperTrade:
    remaining_qty = float(lot["remaining_qty"] or 0.0)
    entry_price = float(lot["fill_price"] or 0.0)
    gross_entry = entry_price * remaining_qty
    gross_notional_total = float(lot["gross_notional"] or 0.0)
    entry_fee = _prorate(float(lot["fee"] or 0.0), remaining_qty, float(lot["quantity"] or 0.0))
    entry_slippage = _prorate(float(lot["slippage"] or 0.0), remaining_qty, float(lot["quantity"] or 0.0))
    latest_price = None
    unrealized = None
    if isinstance(position_mark, dict):
        if position_mark.get("last_price") is not None:
            latest_price = float(position_mark["last_price"])
        quantity = float(position_mark.get("quantity") or 0.0)
        unrealized_total = position_mark.get("unrealized_pnl")
        if unrealized_total is not None and quantity > EPSILON:
            unrealized = _prorate(float(unrealized_total), remaining_qty, quantity)
    return CryptoPaperTrade(
        trade_id=f"crypto-trade-{trade_index:04d}",
        symbol=symbol,
        entry_fill_id=str(lot.get("fill_id") or ""),
        exit_fill_id=None,
        exit_event_id=None,
        entry_time=str(lot.get("entry_time") or ""),
        exit_time=None,
        side="LONG",
        quantity=remaining_qty,
        entry_price=entry_price,
        exit_price=None,
        gross_entry_notional=(gross_notional_total * remaining_qty / float(lot["quantity"] or 1.0)) if abs(float(lot["quantity"] or 0.0)) > EPSILON else gross_entry,
        gross_exit_notional=None,
        entry_fee=entry_fee,
        exit_fee=0.0,
        total_fees=entry_fee,
        entry_slippage=entry_slippage,
        exit_slippage=0.0,
        total_slippage=entry_slippage,
        gross_pnl=None,
        net_pnl=None,
        return_pct=None,
        holding_seconds=None,
        exit_reason=None,
        result="OPEN",
        metadata={
            "last_price": latest_price,
            "unrealized_pnl": unrealized,
            "entry_metadata": dict(lot.get("metadata") or {}),
        },
    )


def _match_exit_event(exit_lookup: dict[str, list[dict[str, Any]]], sell_fill: dict[str, Any], symbol: str) -> dict[str, Any] | None:
    candidates = exit_lookup.get(symbol) or []
    if not candidates:
        return None
    sell_time = _parse_datetime(sell_fill.get("filled_at")) or datetime.min
    for index, event in enumerate(candidates):
        event_time = _parse_datetime(event.get("exited_at")) or datetime.min
        if abs((sell_time - event_time).total_seconds()) <= 1.0:
            return candidates.pop(index)
    return candidates.pop(0)


def _trade_brief(trade: CryptoPaperTrade) -> dict[str, Any]:
    return {
        "trade_id": trade.trade_id,
        "symbol": trade.symbol,
        "net_pnl": trade.net_pnl,
        "return_pct": trade.return_pct,
        "exit_reason": trade.exit_reason,
    }


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _prorate(total: float, part: float, whole: float) -> float:
    if abs(whole) <= EPSILON:
        return 0.0
    return float(total) * (float(part) / float(whole))


def _max_streak(trades: list[CryptoPaperTrade], target: str) -> int:
    best = 0
    current = 0
    for trade in trades:
        if trade.result == target:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item)
        if text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
