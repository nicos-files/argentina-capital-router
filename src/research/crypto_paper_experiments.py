from __future__ import annotations

import itertools
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.execution.crypto_paper_evaluation import (
    build_crypto_paper_trade_log,
    build_exit_reason_breakdown,
    build_fee_slippage_report,
    compute_crypto_paper_strategy_metrics,
)
from src.execution.crypto_paper_exits import evaluate_crypto_exit_triggers
from src.execution.crypto_paper_ledger import CryptoPaperLedger
from src.execution.crypto_paper_models import (
    CryptoPaperExecutionConfig,
    CryptoPaperExitEvent,
    CryptoPaperFill,
)
from src.strategies.crypto_intraday_baseline import (
    DEFAULT_CRYPTO_INTRADAY_STRATEGY_CONFIG,
    IntradayCryptoBaselineStrategy,
)


DEFAULT_EXPERIMENT_MAX_CONFIGS = 100
EPSILON = 1e-12


def load_crypto_paper_experiment_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    text = config_path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError("Empty experiment config.")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("Experiment config must be a JSON object.")
    return payload


def load_crypto_paper_experiment_candles(path: str | Path) -> dict[str, list[dict[str, Any]]]:
    candles_path = Path(path)
    if not candles_path.exists():
        raise FileNotFoundError(f"Missing candles file: {candles_path}")
    if candles_path.suffix.lower() == ".json":
        return _load_candles_json(candles_path)
    if candles_path.suffix.lower() == ".csv":
        return _load_candles_csv(candles_path)
    raise ValueError("Unsupported candles file format. Use JSON or CSV.")


def expand_crypto_paper_parameter_grid(
    experiment_config: dict[str, Any],
    *,
    max_configs: int | None = None,
    allow_large_grid: bool = False,
) -> list[dict[str, Any]]:
    grid = experiment_config.get("grid")
    if not isinstance(grid, dict) or not grid:
        raise ValueError("Experiment grid is required.")
    max_allowed = int(max_configs or experiment_config.get("max_configs") or DEFAULT_EXPERIMENT_MAX_CONFIGS)
    keys = list(grid.keys())
    values: list[list[Any]] = []
    for key in keys:
        raw = grid.get(key)
        if not isinstance(raw, list) or not raw:
            raise ValueError(f"Grid parameter '{key}' must be a non-empty list.")
        values.append(list(raw))
    size = 1
    for items in values:
        size *= len(items)
    if size > max_allowed and not allow_large_grid and not bool(experiment_config.get("allow_large_grid")):
        raise ValueError(f"Grid expands to {size} configs, above max_configs={max_allowed}.")
    results: list[dict[str, Any]] = []
    for index, combo in enumerate(itertools.product(*values), start=1):
        params = dict(zip(keys, combo))
        results.append(
            {
                "config_id": f"cfg-{index:03d}",
                "params": params,
            }
        )
    return results


def run_crypto_paper_experiments(
    *,
    experiment_config: dict[str, Any],
    candles_by_symbol: dict[str, list[dict[str, Any]]],
    output_dir: str | Path,
    max_configs: int | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Path]]:
    warnings: list[str] = ["Paper-only experiments; no real execution occurred."]
    normalized_candles = {
        str(symbol).upper(): _normalize_candle_rows(list(rows or []))
        for symbol, rows in dict(candles_by_symbol or {}).items()
    }
    configs = expand_crypto_paper_parameter_grid(experiment_config, max_configs=max_configs)
    ranked_results: list[dict[str, Any]] = []
    started_at = datetime.utcnow().isoformat()
    for candidate in configs:
        result = _run_single_config(
            experiment_config=experiment_config,
            config_id=str(candidate["config_id"]),
            params=dict(candidate["params"]),
            candles_by_symbol=normalized_candles,
        )
        ranked_results.append(result)
    rankings, ranking_warnings = rank_crypto_paper_experiment_results(
        ranked_results,
        experiment_config.get("ranking") if isinstance(experiment_config.get("ranking"), dict) else {},
    )
    warnings.extend(ranking_warnings)
    summary = {
        "experiment_name": str(experiment_config.get("experiment_name") or "crypto_paper_experiment"),
        "started_at": started_at,
        "completed_at": datetime.utcnow().isoformat(),
        "symbols": sorted(normalized_candles.keys()),
        "configs_tested": len(ranked_results),
        "eligible_configs": sum(1 for item in ranked_results if bool(item.get("eligible"))),
        "best_config_id": rankings[0]["config_id"] if rankings else None,
        "best_config": rankings[0]["config"] if rankings else None,
        "best_metrics": rankings[0]["metrics"] if rankings else None,
        "worst_config_id": rankings[-1]["config_id"] if rankings else None,
        "ranking": {
            "primary_metric": str((experiment_config.get("ranking") or {}).get("primary_metric") or "expectancy"),
            "secondary_metrics": list((experiment_config.get("ranking") or {}).get("secondary_metrics") or []),
        },
        "warnings": _dedupe(warnings),
        "metadata": {
            "paper_only": True,
            "live_trading": False,
            "winning_config_applied": False,
        },
    }
    written = write_crypto_paper_experiment_artifacts(
        output_dir=output_dir,
        summary=summary,
        results=ranked_results,
        rankings=rankings,
    )
    return summary, rankings, written


def rank_crypto_paper_experiment_results(
    results: list[dict[str, Any]],
    ranking_config: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    min_closed_trades = int(ranking_config.get("min_closed_trades") or 5)
    max_drawdown_threshold = ranking_config.get("max_drawdown_pct")
    if max_drawdown_threshold is not None:
        max_drawdown_threshold = float(max_drawdown_threshold)
    primary_metric = str(ranking_config.get("primary_metric") or "expectancy")
    secondary_metrics = list(ranking_config.get("secondary_metrics") or ["profit_factor", "net_profit", "max_drawdown_pct", "closed_trades_count"])

    ranked_items: list[dict[str, Any]] = []
    for item in results:
        metrics = dict(item.get("metrics") or {})
        disqualifications = list(item.get("disqualification_reasons") or [])
        closed_trades = int(metrics.get("closed_trades_count") or 0)
        max_drawdown_pct = item.get("max_drawdown_pct")
        if closed_trades < min_closed_trades:
            disqualifications.append("closed_trades_below_min")
        if max_drawdown_threshold is not None and max_drawdown_pct is not None and float(max_drawdown_pct) < max_drawdown_threshold:
            disqualifications.append("max_drawdown_below_threshold")
        eligible = not disqualifications
        item["disqualification_reasons"] = _dedupe(disqualifications)
        item["eligible"] = eligible
        item["ranking_score"] = _numeric_metric(metrics.get(primary_metric))
        ranked_items.append(item)

    eligible_exists = any(bool(item.get("eligible")) for item in ranked_items)
    if not eligible_exists and ranked_items:
        warnings.append("No eligible configs met the ranking constraints; returning best available result.")
    ranked_items.sort(key=lambda item: _ranking_sort_key(item, primary_metric, secondary_metrics), reverse=True)
    for rank, item in enumerate(ranked_items, start=1):
        item["rank"] = rank
    return ranked_items, warnings


def write_crypto_paper_experiment_artifacts(
    *,
    output_dir: str | Path,
    summary: dict[str, Any],
    results: list[dict[str, Any]],
    rankings: list[dict[str, Any]],
) -> dict[str, Path]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    results_payload = {
        "summary": summary,
        "results": results,
        "paper_only": True,
        "live_trading": False,
    }
    metrics_by_config = {
        item["config_id"]: {
            "eligible": item["eligible"],
            "net_profit": item["net_profit"],
            "expectancy": item["expectancy"],
            "profit_factor": item["profit_factor"],
            "win_rate": item["win_rate"],
            "max_drawdown_pct": item["max_drawdown_pct"],
            "closed_trades_count": item["closed_trades_count"],
            "open_trades_count": item["open_trades_count"],
            "total_fees": item["total_fees"],
            "total_slippage": item["total_slippage"],
            "ranking_score": item["ranking_score"],
        }
        for item in results
    }
    trade_logs = {
        item["config_id"]: {
            "closed_trades": item["trade_log"]["closed_trades"],
            "open_trades": item["trade_log"]["open_trades"],
        }
        for item in results
    }
    payloads = {
        "crypto_paper_experiment_results.json": results_payload,
        "crypto_paper_experiment_rankings.json": rankings,
        "crypto_paper_experiment_trade_logs.json": trade_logs,
        "crypto_paper_experiment_metrics_by_config.json": metrics_by_config,
    }
    written: dict[str, Path] = {}
    for filename, payload in payloads.items():
        path = root / filename
        path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
        written[filename] = path
    report_path = root / "crypto_paper_experiment_report.md"
    report_path.write_text(build_crypto_paper_experiment_report(summary, rankings), encoding="utf-8")
    written[report_path.name] = report_path
    return written


def build_crypto_paper_experiment_report(summary: dict[str, Any], rankings: list[dict[str, Any]]) -> str:
    best = rankings[0] if rankings else None
    worst = rankings[-1] if rankings else None
    lines = [
        "# Crypto Paper Parameter Experiment",
        "",
        "## Summary",
        f"- Experiment name: {summary.get('experiment_name')}",
        f"- Symbols: {', '.join(summary.get('symbols') or [])}",
        f"- Configs tested: {summary.get('configs_tested', 0)}",
        f"- Eligible configs: {summary.get('eligible_configs', 0)}",
        f"- Best config: {summary.get('best_config_id')}",
        f"- Best expectancy: {(best or {}).get('expectancy')}",
        f"- Best profit factor: {(best or {}).get('profit_factor')}",
        f"- Best net P&L: {(best or {}).get('net_profit')}",
        f"- Best max drawdown %: {(best or {}).get('max_drawdown_pct')}",
        "",
        "## Ranking",
        "| Rank | Config ID | Eligible | Closed trades | Net P&L | Expectancy | Profit factor | Win rate | Max drawdown % | Total fees |",
        "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in rankings:
        lines.append(
            f"| {item.get('rank')} | {item.get('config_id')} | {item.get('eligible')} | "
            f"{item.get('closed_trades_count')} | {float(item.get('net_profit') or 0.0):.6f} | "
            f"{item.get('expectancy')} | {item.get('profit_factor')} | {item.get('win_rate')} | "
            f"{item.get('max_drawdown_pct')} | {float(item.get('total_fees') or 0.0):.6f} |"
        )
    lines.extend(
        [
            "",
            "## Best Config Details",
        ]
    )
    if best:
        lines.extend(
            [
                f"- Config ID: {best.get('config_id')}",
                f"- Parameters: {best.get('config')}",
                f"- Metrics: {best.get('metrics')}",
                f"- Warnings: {best.get('warnings')}",
            ]
        )
    else:
        lines.append("- None.")
    lines.extend(["", "## Worst Config Details"])
    if worst:
        lines.extend(
            [
                f"- Config ID: {worst.get('config_id')}",
                f"- Parameters: {worst.get('config')}",
                f"- Metrics: {worst.get('metrics')}",
            ]
        )
    else:
        lines.append("- None.")
    lines.extend(["", "## Disqualified / Low Sample Configs"])
    disqualified = [item for item in rankings if item.get("disqualification_reasons")]
    if not disqualified:
        lines.append("- None.")
    else:
        for item in disqualified:
            lines.append(f"- {item.get('config_id')}: {', '.join(item.get('disqualification_reasons') or [])}")
    lines.extend(
        [
            "",
            "## Notes",
            "- Paper-only.",
            "- Simulated fees and slippage.",
            "- No live orders placed.",
            "- No broker integration.",
            "- Winning config was not automatically applied.",
            "- Beware overfitting.",
        ]
    )
    return "\n".join(lines) + "\n"


def _run_single_config(
    *,
    experiment_config: dict[str, Any],
    config_id: str,
    params: dict[str, Any],
    candles_by_symbol: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    warnings: list[str] = ["Drawdown calculated from event-level equity points, not every candle."]
    config = dict(DEFAULT_CRYPTO_INTRADAY_STRATEGY_CONFIG)
    config.update(
        {
            "timeframe": experiment_config.get("timeframe", config["timeframe"]),
            "max_paper_notional": float(experiment_config.get("max_paper_notional") or config["max_paper_notional"]),
            "allow_short": bool(experiment_config.get("allow_short", config["allow_short"])),
        }
    )
    config.update(params)
    validation_errors = _validate_candidate_config(config, experiment_config, candles_by_symbol)
    if validation_errors:
        return {
            "config_id": config_id,
            "config": config,
            "symbols": sorted(candles_by_symbol.keys()),
            "closed_trades_count": 0,
            "open_trades_count": 0,
            "net_profit": 0.0,
            "expectancy": None,
            "profit_factor": None,
            "win_rate": None,
            "max_drawdown_pct": None,
            "total_fees": 0.0,
            "total_slippage": 0.0,
            "ranking_score": None,
            "eligible": False,
            "disqualification_reasons": validation_errors,
            "warnings": validation_errors,
            "trade_log": {"closed_trades": [], "open_trades": []},
            "metrics": {},
            "metadata": {"paper_only": True, "live_trading": False, "rejected_orders_count": 0},
        }

    strategy = IntradayCryptoBaselineStrategy(config)
    ledger = CryptoPaperLedger(
        CryptoPaperExecutionConfig(
            starting_cash=float(experiment_config.get("starting_cash") or 100.0),
            quote_currency=str(experiment_config.get("quote_currency") or "USDT"),
            fee_bps=float(experiment_config.get("fee_bps") or 0.0),
            slippage_bps=float(experiment_config.get("slippage_bps") or 0.0),
            max_notional_per_order=float(experiment_config.get("max_paper_notional") or config["max_paper_notional"]),
            min_notional_per_order=float(experiment_config.get("min_notional_per_order") or 0.0),
            allow_short=False,
            allow_live_trading=False,
            enable_exits=True,
        )
    )
    fills: list[CryptoPaperFill] = []
    exit_events: list[CryptoPaperExitEvent] = []
    rejected_orders_count = 0
    history_by_symbol: dict[str, list[dict[str, Any]]] = {symbol: [] for symbol in candles_by_symbol}
    latest_marks: dict[str, float] = {}
    equity_points: list[dict[str, Any]] = []
    all_events = _build_symbol_events(candles_by_symbol)

    for event_index, event in enumerate(all_events, start=1):
        symbol = str(event["symbol"])
        timestamp = event["timestamp"]
        candle = dict(event["candle"])
        current_close = float(candle["close"])

        latest_marks[symbol] = current_close
        existing = ledger.positions.get(symbol)
        if existing is not None and float(existing.quantity or 0.0) > EPSILON:
            events = evaluate_crypto_exit_triggers(
                positions=[existing],
                candles_by_symbol={symbol: [candle]},
                as_of=timestamp,
                config=ledger.config,
            )
            if events:
                exit_event = events[0]
                exit_fill = _build_exit_fill(
                    config=ledger.config,
                    symbol=symbol,
                    event=exit_event,
                    index=len(fills) + 1,
                )
                try:
                    ledger.apply_sell_fill(exit_fill)
                    exit_events.append(
                        CryptoPaperExitEvent(
                            exit_id=exit_event.exit_id,
                            symbol=exit_event.symbol,
                            position_quantity_before=exit_event.position_quantity_before,
                            exit_quantity=exit_event.exit_quantity,
                            exit_reason=exit_event.exit_reason,
                            trigger_price=exit_event.trigger_price,
                            fill_price=exit_fill.fill_price,
                            gross_notional=exit_fill.gross_notional,
                            fee=exit_fill.fee,
                            slippage=exit_fill.slippage,
                            realized_pnl=((exit_fill.fill_price - float(existing.avg_entry_price)) * exit_fill.quantity) - exit_fill.fee,
                            exited_at=timestamp,
                            source=exit_event.source,
                            metadata=dict(exit_event.metadata or {}),
                        )
                    )
                    fills.append(exit_fill)
                except ValueError:
                    rejected_orders_count += 1

        history_by_symbol[symbol].append(candle)
        if symbol not in ledger.positions:
            frame = pd.DataFrame(history_by_symbol[symbol])
            if not frame.empty and "timestamp" in frame.columns:
                frame = frame.rename(columns={"timestamp": "date"})
                frame["date"] = pd.to_datetime(frame["date"], utc=False)
            signal = strategy.evaluate(
                symbol=symbol,
                candles=frame,
                latest_quote={"last_price": current_close},
                provider_healthy=True,
            )
            if signal is not None and str(signal.action).upper() == "BUY":
                buy_fill = _build_buy_fill(
                    config=ledger.config,
                    symbol=symbol,
                    price=float(signal.entry_price or current_close),
                    notional=float(signal.max_notional or config["max_paper_notional"]),
                    timestamp=timestamp,
                    index=len(fills) + 1,
                    metadata={
                        "stop_loss": signal.stop_loss,
                        "take_profit": signal.take_profit,
                        "signal_reason": signal.reason,
                        "signal_score": signal.score,
                    },
                )
                if ledger.can_afford(buy_fill.gross_notional, buy_fill.fee):
                    ledger.apply_buy_fill(buy_fill)
                    fills.append(buy_fill)
                else:
                    rejected_orders_count += 1

        ledger.mark_to_market(dict(latest_marks), timestamp)
        snapshot = ledger.snapshot(timestamp, metadata={"config_id": config_id})
        equity_points.append(
            {
                "timestamp": timestamp.isoformat(),
                "equity": snapshot.equity,
                "cash": snapshot.cash,
                "positions_value": snapshot.positions_value,
            }
        )

    final_time = all_events[-1]["timestamp"] if all_events else datetime.utcnow()
    final_snapshot = ledger.snapshot(final_time, metadata={"config_id": config_id})
    payloads = {
        "fills": [fill.to_dict() for fill in fills],
        "exit_events": [event.to_dict() for event in exit_events],
        "orders": [],
        "snapshot": final_snapshot.to_dict(),
        "history": None,
        "equity_curve": None,
    }
    closed_trades, open_trades, pairing_warnings = build_crypto_paper_trade_log(payloads)
    warnings.extend(pairing_warnings)
    metrics_obj = compute_crypto_paper_strategy_metrics(closed_trades, open_trades, warnings=warnings)
    exit_breakdown = build_exit_reason_breakdown(closed_trades)
    fee_report = build_fee_slippage_report(closed_trades, metrics_obj)
    max_drawdown_pct = _max_drawdown_pct(equity_points)
    metrics = metrics_obj.to_dict()
    metrics["max_drawdown_pct"] = max_drawdown_pct
    metrics["rejected_orders_count"] = rejected_orders_count
    result = {
        "config_id": config_id,
        "config": config,
        "symbols": sorted(candles_by_symbol.keys()),
        "closed_trades_count": metrics_obj.closed_trades_count,
        "open_trades_count": metrics_obj.open_trades_count,
        "net_profit": metrics_obj.net_profit,
        "expectancy": metrics_obj.expectancy,
        "profit_factor": metrics_obj.profit_factor,
        "win_rate": metrics_obj.win_rate,
        "max_drawdown_pct": max_drawdown_pct,
        "total_fees": metrics_obj.total_fees,
        "total_slippage": metrics_obj.total_slippage,
        "ranking_score": None,
        "eligible": False,
        "disqualification_reasons": [],
        "warnings": metrics_obj.warnings,
        "trade_log": {
            "closed_trades": [trade.to_dict() for trade in closed_trades],
            "open_trades": [trade.to_dict() for trade in open_trades],
        },
        "metrics": metrics,
        "exit_breakdown": exit_breakdown,
        "fee_report": fee_report,
        "equity_curve": equity_points,
        "metadata": {
            "paper_only": True,
            "live_trading": False,
            "rejected_orders_count": rejected_orders_count,
            "trade_level_drawdown": True,
        },
    }
    return result


def _load_candles_json(path: Path) -> dict[str, list[dict[str, Any]]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError("Empty candles file.")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("Candles JSON must be an object keyed by symbol.")
    result: dict[str, list[dict[str, Any]]] = {}
    for symbol, rows in payload.items():
        if not isinstance(rows, list):
            continue
        result[str(symbol).upper()] = _normalize_candle_rows(rows)
    return result


def _load_candles_csv(path: Path) -> dict[str, list[dict[str, Any]]]:
    frame = pd.read_csv(path)
    required = {"symbol", "timestamp", "open", "high", "low", "close"}
    if not required.issubset(frame.columns):
        missing = sorted(required - set(frame.columns))
        raise ValueError(f"Missing CSV candle columns: {missing}")
    result: dict[str, list[dict[str, Any]]] = {}
    for symbol, group in frame.groupby("symbol"):
        rows = group.to_dict(orient="records")
        result[str(symbol).upper()] = _normalize_candle_rows(rows)
    return result


def _normalize_candle_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        timestamp = _parse_timestamp(row.get("timestamp") or row.get("date"))
        try:
            open_price = float(row["open"])
            high = float(row["high"])
            low = float(row["low"])
            close = float(row["close"])
        except (KeyError, TypeError, ValueError):
            continue
        if timestamp is None:
            continue
        normalized.append(
            {
                "timestamp": timestamp,
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": float(row.get("volume") or 0.0),
            }
        )
    normalized.sort(key=lambda item: item["timestamp"])
    return normalized


def _validate_candidate_config(
    config: dict[str, Any],
    experiment_config: dict[str, Any],
    candles_by_symbol: dict[str, list[dict[str, Any]]],
) -> list[str]:
    errors: list[str] = []
    fast = int(config.get("fast_ma_window") or 0)
    slow = int(config.get("slow_ma_window") or 0)
    if fast <= 0 or slow <= 0 or fast >= slow:
        errors.append("fast_ma_window_must_be_less_than_slow_ma_window")
    for key in ("stop_loss_pct", "take_profit_pct", "max_paper_notional", "max_volatility_pct"):
        if float(config.get(key) or 0.0) <= 0.0:
            errors.append(f"{key}_must_be_positive")
    if float(config.get("min_abs_signal_strength") or 0.0) < 0.0:
        errors.append("min_abs_signal_strength_must_be_non_negative")
    if float(experiment_config.get("starting_cash") or 0.0) <= 0.0:
        errors.append("starting_cash_must_be_positive")
    if float(experiment_config.get("fee_bps") or 0.0) < 0.0:
        errors.append("fee_bps_must_be_non_negative")
    if float(experiment_config.get("slippage_bps") or 0.0) < 0.0:
        errors.append("slippage_bps_must_be_non_negative")
    requested_symbols = list(experiment_config.get("symbols") or candles_by_symbol.keys())
    for symbol in requested_symbols:
        if str(symbol).upper() not in candles_by_symbol:
            errors.append(f"missing_symbol_candles:{str(symbol).upper()}")
    return _dedupe(errors)


def _build_symbol_events(candles_by_symbol: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for symbol, rows in candles_by_symbol.items():
        for row in rows:
            events.append({"symbol": symbol, "timestamp": row["timestamp"], "candle": dict(row)})
    events.sort(key=lambda item: (item["timestamp"], item["symbol"]))
    return events


def _build_buy_fill(
    *,
    config: CryptoPaperExecutionConfig,
    symbol: str,
    price: float,
    notional: float,
    timestamp: datetime,
    index: int,
    metadata: dict[str, Any],
) -> CryptoPaperFill:
    slippage = float(price) * float(config.slippage_bps) / 10000.0
    fill_price = float(price) + slippage
    gross_notional = float(notional)
    fee = gross_notional * float(config.fee_bps) / 10000.0
    quantity = gross_notional / fill_price if fill_price > EPSILON else 0.0
    return CryptoPaperFill(
        fill_id=f"exp-buy-fill-{index:04d}",
        order_id=f"exp-buy-order-{index:04d}",
        symbol=symbol,
        side="BUY",
        quantity=quantity,
        fill_price=fill_price,
        gross_notional=gross_notional,
        fee=fee,
        slippage=slippage,
        net_notional=gross_notional + fee,
        filled_at=timestamp,
        metadata=dict(metadata),
    )


def _build_exit_fill(
    *,
    config: CryptoPaperExecutionConfig,
    symbol: str,
    event: CryptoPaperExitEvent,
    index: int,
) -> CryptoPaperFill:
    reference_price = float(event.trigger_price or 0.0)
    slippage = reference_price * float(config.slippage_bps) / 10000.0
    fill_price = reference_price - slippage
    gross_notional = float(event.exit_quantity) * fill_price
    fee = gross_notional * float(config.fee_bps) / 10000.0
    return CryptoPaperFill(
        fill_id=f"exp-sell-fill-{index:04d}",
        order_id=f"exp-sell-order-{index:04d}",
        symbol=symbol,
        side="SELL",
        quantity=float(event.exit_quantity),
        fill_price=fill_price,
        gross_notional=gross_notional,
        fee=fee,
        slippage=slippage,
        net_notional=gross_notional - fee,
        filled_at=event.exited_at,
        metadata={"exit_reason": event.exit_reason, **dict(event.metadata or {})},
    )


def _max_drawdown_pct(points: list[dict[str, Any]]) -> float | None:
    if not points:
        return None
    peak: float | None = None
    max_drawdown = 0.0
    for point in points:
        equity = float(point.get("equity") or 0.0)
        if peak is None or equity > peak:
            peak = equity
        if peak is None or peak <= EPSILON:
            continue
        drawdown_pct = ((equity - peak) / peak) * 100.0
        if drawdown_pct < max_drawdown:
            max_drawdown = drawdown_pct
    return max_drawdown


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if value is None:
        return None
    try:
        return pd.Timestamp(value).to_pydatetime()
    except Exception:
        return None


def _numeric_metric(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return float("-inf")
    if pd.isna(numeric):
        return float("-inf")
    return numeric


def _ranking_sort_key(item: dict[str, Any], primary_metric: str, secondary_metrics: list[str]) -> tuple[Any, ...]:
    metrics = dict(item.get("metrics") or {})
    values = [1 if item.get("eligible") else 0]
    values.append(_numeric_metric(metrics.get(primary_metric)))
    for key in secondary_metrics:
        if key == "max_drawdown_pct":
            values.append(_numeric_metric(item.get("max_drawdown_pct")))
        else:
            values.append(_numeric_metric(metrics.get(key, item.get(key))))
    return tuple(values)


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
