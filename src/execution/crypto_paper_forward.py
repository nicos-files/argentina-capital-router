from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from src.decision_intel.contracts.recommendations.recommendation_models import RecommendationOutput
from src.engines import EngineContext, IntradayCryptoEngine
from src.execution.crypto_paper_daily_close import close_crypto_paper_day
from src.execution.crypto_paper_evaluation import evaluate_crypto_paper_strategy
from src.execution.crypto_paper_exits import evaluate_crypto_exit_triggers
from src.execution.crypto_paper_history import update_crypto_paper_history
from src.execution.crypto_paper_ledger import CryptoPaperLedger
from src.execution.crypto_paper_models import (
    CryptoPaperExecutionConfig,
    CryptoPaperExecutionResult,
    CryptoPaperExitEvent,
    CryptoPaperFill,
    CryptoPaperOrder,
    CryptoPaperPortfolioSnapshot,
    CryptoPaperPosition,
)
from src.market_data.providers import BinanceSpotMarketDataProvider, ProviderHealth
from src.risk import RiskEngine


def load_crypto_paper_forward_candidate(path: str | Path) -> dict[str, Any]:
    candidate_path = Path(path)
    text = candidate_path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError("Empty candidate config file.")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("Candidate config must be a JSON object.")
    return payload


def validate_crypto_paper_forward_candidate(candidate_config: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    info: list[str] = [
        "Paper-only forward runner.",
        "No live orders are placed.",
        "Manual review still required.",
    ]
    strategy = dict(candidate_config.get("strategy") or {})
    symbols = list(candidate_config.get("symbols") or [])
    if not strategy:
        errors.append("missing_strategy_config")
    if not isinstance(symbols, list) or not symbols:
        errors.append("missing_symbols_config")
    if bool(strategy.get("allow_short")):
        errors.append("allow_short_must_remain_false")
    if not bool(strategy.get("enabled")):
        errors.append("strategy_enabled_must_be_true_for_paper_forward")
    enabled_strategy_symbols = [
        str(item.get("symbol") or "").upper()
        for item in symbols
        if isinstance(item, dict) and item.get("enabled") and item.get("strategy_enabled")
    ]
    if not enabled_strategy_symbols:
        errors.append("no_strategy_enabled_symbols")
    for item in symbols:
        if not isinstance(item, dict):
            continue
        if bool(item.get("live_enabled")):
            errors.append(f"live_enabled_true:{item.get('symbol')}")
    if _has_sensitive_keys(candidate_config, {"api_key", "apikey", "secret", "token"}):
        errors.append("candidate_contains_api_keys")
    if _has_sensitive_keys(candidate_config, {"broker", "broker_settings", "broker_api"}):
        errors.append("candidate_contains_broker_settings")
    fast = _safe_int(strategy.get("fast_ma_window"))
    slow = _safe_int(strategy.get("slow_ma_window"))
    if fast is None or slow is None or fast >= slow:
        errors.append("fast_ma_window_must_be_less_than_slow_ma_window")
    if _safe_float(strategy.get("stop_loss_pct")) in (None, 0.0):
        errors.append("stop_loss_pct_must_be_positive")
    if _safe_float(strategy.get("take_profit_pct")) in (None, 0.0):
        errors.append("take_profit_pct_must_be_positive")
    if _safe_float(strategy.get("max_paper_notional")) in (None, 0.0):
        errors.append("max_paper_notional_must_be_positive")
    try:
        json.dumps(candidate_config)
    except Exception as exc:
        errors.append(f"candidate_not_json_serializable:{exc}")

    return {
        "eligible_to_run": not errors,
        "errors": _dedupe(errors),
        "warnings": _dedupe(warnings),
        "info": _dedupe(info),
        "paper_only": True,
        "live_trading": False,
        "strategy_enabled_symbols": enabled_strategy_symbols,
        "safety_assertions": {
            "live_enabled_all_symbols": any(bool((item or {}).get("live_enabled")) for item in symbols if isinstance(item, dict)),
            "api_keys_present": _has_sensitive_keys(candidate_config, {"api_key", "apikey", "secret", "token"}),
            "broker_settings_present": _has_sensitive_keys(candidate_config, {"broker", "broker_settings", "broker_api"}),
        },
    }


class StaticCryptoPaperForwardProvider:
    provider_name = "static_crypto_forward"

    def __init__(self, bundle: dict[str, Any]):
        quotes, candles = _normalize_prices_bundle(bundle)
        self._quotes = quotes
        self._candles = candles

    def health_check(self) -> ProviderHealth:
        status = "healthy" if (self._quotes or self._candles) else "unhealthy"
        message = "static bundle loaded" if status == "healthy" else "empty static price bundle"
        return ProviderHealth(
            provider_name=self.provider_name,
            status=status,
            message=message,
            checked_at_utc=datetime.now(timezone.utc).isoformat(),
        )

    def get_latest_quote(self, symbol: str) -> dict[str, Any]:
        normalized = str(symbol).upper()
        quote = self._quotes.get(normalized)
        if quote is None:
            raise ValueError(f"missing static quote for {normalized}")
        return dict(quote)

    def get_historical_bars(
        self,
        symbol: str,
        timeframe: str,
        start: str | None = None,
        end: str | None = None,
        limit: int | None = None,
    ) -> pd.DataFrame:
        normalized = str(symbol).upper()
        rows = list(self._candles.get(normalized) or [])
        if start:
            start_ts = pd.Timestamp(start)
            rows = [row for row in rows if pd.Timestamp(row["date"]) >= start_ts]
        if end:
            end_ts = pd.Timestamp(end)
            rows = [row for row in rows if pd.Timestamp(row["date"]) <= end_ts]
        if limit is not None:
            rows = rows[-int(limit) :]
        return pd.DataFrame(rows)


def run_crypto_paper_forward(
    *,
    candidate_config: dict[str, Any] | str | Path,
    artifacts_dir: str | Path = "artifacts/crypto_paper",
    as_of: datetime | str | None = None,
    prices_json: str | Path | None = None,
    dry_run: bool = True,
    provider: Any | None = None,
    engine: IntradayCryptoEngine | None = None,
    executor: Any | None = None,
) -> dict[str, Any]:
    artifact_root = Path(artifacts_dir)
    paper_forward_dir = artifact_root / "paper_forward"
    paper_forward_dir.mkdir(parents=True, exist_ok=True)

    candidate_payload = (
        load_crypto_paper_forward_candidate(candidate_config)
        if isinstance(candidate_config, (str, Path))
        else dict(candidate_config)
    )
    validation = validate_crypto_paper_forward_candidate(candidate_payload)
    if prices_json is None and provider is None and not _flag("ENABLE_CRYPTO_MARKET_DATA"):
        validation["errors"] = _dedupe(list(validation["errors"]) + ["market_data_disabled_without_prices_json"])
        validation["eligible_to_run"] = False

    if prices_json is not None:
        bundle = json.loads(Path(prices_json).read_text(encoding="utf-8"))
        active_provider = StaticCryptoPaperForwardProvider(bundle)
        injected_bundle = bundle
    else:
        injected_bundle = None
        active_provider = provider or BinanceSpotMarketDataProvider()

    health = active_provider.health_check()
    validation["provider_health"] = {
        "provider_name": health.provider_name,
        "status": health.status,
        "message": health.message,
        "checked_at_utc": health.checked_at_utc,
    }
    if str(health.status).lower() != "healthy":
        validation["warnings"] = _dedupe(list(validation["warnings"]) + [f"provider_unhealthy:{health.message}"])

    validation_path = paper_forward_dir / "crypto_paper_forward_validation.json"
    validation_path.write_text(json.dumps(validation, sort_keys=True, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")

    effective_as_of = _parse_as_of(as_of)
    if not validation["eligible_to_run"]:
        result = {
            "status": "FAILED",
            "paper_only": True,
            "dry_run": bool(dry_run),
            "candidate_config_used": str(candidate_config) if isinstance(candidate_config, (str, Path)) else "in_memory",
            "warnings": list(validation["warnings"]),
            "validation_errors": list(validation["errors"]),
            "artifacts": {"crypto_paper_forward_validation.json": str(validation_path)},
            "live_trading": False,
        }
        result_path = paper_forward_dir / "crypto_paper_forward_result.json"
        result_path.write_text(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
        report_path = paper_forward_dir / "crypto_paper_forward_report.md"
        report_path.write_text(_build_failed_report(result), encoding="utf-8")
        return result

    warnings: list[str] = list(validation["warnings"])
    step_status = {
        "validation": "SUCCESS",
        "signals": "PENDING",
        "execution": "PENDING",
        "daily_close": "PENDING",
        "history": "PENDING",
        "evaluation": "PENDING",
    }
    active_engine = engine or IntradayCryptoEngine()
    active_executor = executor or __import__("src.execution.crypto_paper_executor", fromlist=["CryptoPaperExecutor"]).CryptoPaperExecutor(
        CryptoPaperExecutionConfig(
            starting_cash=100.0,
            quote_currency=str(candidate_payload.get("default_quote_currency") or "USDT"),
            max_notional_per_order=float((candidate_payload.get("strategy") or {}).get("max_paper_notional") or 25.0),
            enable_exits=True,
        ),
        RiskEngine(),
    )
    ledger = _load_forward_ledger(
        artifact_root=artifact_root,
        config=active_executor.config,
    )

    enabled_symbols = [
        str(item.get("symbol") or "").upper()
        for item in list(candidate_payload.get("symbols") or [])
        if isinstance(item, dict) and item.get("enabled")
    ]
    strategy_enabled_symbols = [
        str(item.get("symbol") or "").upper()
        for item in list(candidate_payload.get("symbols") or [])
        if isinstance(item, dict) and item.get("enabled") and item.get("strategy_enabled")
    ]
    context = EngineContext(
        as_of=effective_as_of,
        run_id=effective_as_of.strftime("%Y%m%d-%H%M"),
        mode="crypto_paper_forward",
        universe=enabled_symbols,
        config={
            "crypto_universe": list(candidate_payload.get("symbols") or []),
            "crypto_strategy": dict(candidate_payload.get("strategy") or {}),
            "crypto_symbols": enabled_symbols,
            "enable_crypto_market_data": True,
        },
        provider_health={
            active_provider.provider_name: {
                "status": health.status,
                "message": health.message,
                "checked_at_utc": health.checked_at_utc,
            }
        },
        metadata={
            "asof_date": effective_as_of.strftime("%Y-%m-%d"),
            "execution_date": effective_as_of.strftime("%Y-%m-%d"),
            "execution_hour": effective_as_of.strftime("%H%M"),
            "crypto_provider_name": active_provider.provider_name,
            "crypto_provider": active_provider,
        },
    )

    engine_result = None
    latest_quotes: dict[str, Any] = {}
    try:
        engine_result = active_engine.run(context)
        step_status["signals"] = "SUCCESS"
        warnings.extend(engine_result.diagnostics.warnings)
        for symbol in sorted(set(strategy_enabled_symbols + list(ledger.positions.keys()))):
            try:
                latest_quotes[symbol] = active_provider.get_latest_quote(symbol)
            except Exception as exc:
                warnings.append(f"Quote retrieval failed for {symbol}: {exc}")
        for item in engine_result.recommendations.recommendations:
            latest_quotes.setdefault(item.asset_id, {"last_price": item.price_used, "ask": item.price_used, "provider": active_provider.provider_name})
    except Exception as exc:
        step_status["signals"] = "FAILED"
        warnings.append(f"signal_engine_failed:{exc}")
        engine_result = _empty_engine_result(context)

    entry_result = None
    exit_result = None
    combined_execution = None
    try:
        entry_result = active_executor.execute(
            recommendations=engine_result.recommendations,
            latest_quotes=latest_quotes,
            as_of=effective_as_of,
            ledger=ledger,
        )
        exit_events = _evaluate_forward_exits(
            provider=active_provider,
            ledger=ledger,
            strategy_config=dict(candidate_payload.get("strategy") or {}),
            as_of=effective_as_of,
            warnings=warnings,
            latest_quotes=latest_quotes,
        )
        exit_result = active_executor.execute(
            recommendations=_empty_recommendations(context),
            latest_quotes=latest_quotes,
            as_of=effective_as_of,
            ledger=ledger,
            exit_events=exit_events,
        )
        combined_execution = _merge_execution_results(entry_result, exit_result, ledger.snapshot(effective_as_of, metadata={"quote_currency": active_executor.config.quote_currency}))
        write_warnings = _write_execution_artifacts(artifact_root=artifact_root, result=combined_execution)
        warnings.extend(write_warnings)
        step_status["execution"] = "SUCCESS"
    except Exception as exc:
        step_status["execution"] = "FAILED"
        warnings.append(f"execution_failed:{exc}")
        combined_execution = _merge_execution_results(
            entry_result or _empty_execution_result(ledger.snapshot(effective_as_of, metadata={})),
            exit_result or _empty_execution_result(ledger.snapshot(effective_as_of, metadata={})),
            ledger.snapshot(effective_as_of, metadata={"quote_currency": active_executor.config.quote_currency}),
        )

    close_result = None
    try:
        price_map = injected_bundle if injected_bundle is not None else latest_quotes
        close_result = close_crypto_paper_day(
            artifacts_dir=artifact_root,
            as_of=effective_as_of,
            output_dir=artifact_root / "daily_close",
            price_map=price_map,
            provider=None if injected_bundle is not None else active_provider,
            provider_health=validation["provider_health"],
        )
        step_status["daily_close"] = "SUCCESS"
        warnings.extend(close_result.warnings)
    except Exception as exc:
        step_status["daily_close"] = "FAILED"
        warnings.append(f"daily_close_failed:{exc}")

    history_result = None
    try:
        entries, points, summary, symbol_attribution, artifacts, history_warnings = update_crypto_paper_history(
            daily_close_dir=artifact_root / "daily_close",
            history_dir=artifact_root / "history",
        )
        history_result = {
            "entries_count": len(entries),
            "equity_points_count": len(points),
            "ending_equity": summary.ending_equity,
            "warnings": history_warnings,
            "artifacts": {name: str(path) for name, path in artifacts.items()},
        }
        step_status["history"] = "SUCCESS"
        warnings.extend(history_warnings)
    except Exception as exc:
        step_status["history"] = "FAILED"
        warnings.append(f"history_failed:{exc}")

    evaluation_result = None
    try:
        closed_trades, open_trades, metrics, exit_breakdown, fee_report, written, eval_warnings = evaluate_crypto_paper_strategy(
            artifacts_dir=artifact_root,
            output_dir=artifact_root / "evaluation",
        )
        evaluation_result = {
            "closed_trades_count": len(closed_trades),
            "open_trades_count": len(open_trades),
            "net_profit": metrics.net_profit,
            "win_rate": metrics.win_rate,
            "expectancy": metrics.expectancy,
            "profit_factor": metrics.profit_factor,
            "fee_drag_pct_of_gross_pnl": metrics.fee_drag_pct_of_gross_pnl,
            "warnings": eval_warnings,
            "artifacts": {name: str(path) for name, path in written.items()},
        }
        step_status["evaluation"] = "SUCCESS"
        warnings.extend(eval_warnings)
    except Exception as exc:
        step_status["evaluation"] = "FAILED"
        warnings.append(f"evaluation_failed:{exc}")

    tickets = build_crypto_manual_trade_tickets(
        recommendations=engine_result.recommendations,
        execution_result=combined_execution,
        engine_warnings=list(engine_result.diagnostics.warnings if engine_result else []),
        provider_warnings=list(warnings),
    )
    ticket_artifacts = write_crypto_manual_trade_tickets(
        output_dir=paper_forward_dir,
        tickets=tickets,
    )

    final_snapshot = combined_execution.portfolio_snapshot
    result = {
        "status": "SUCCESS" if all(value == "SUCCESS" for value in step_status.values()) else "PARTIAL",
        "paper_only": True,
        "dry_run": bool(dry_run),
        "candidate_config_used": str(candidate_config) if isinstance(candidate_config, (str, Path)) else "in_memory",
        "symbols_evaluated": enabled_symbols,
        "recommendations_count": len(engine_result.recommendations.recommendations),
        "fills_count": len(combined_execution.fills),
        "exits_count": len(combined_execution.exit_events),
        "realized_pnl": float(final_snapshot.realized_pnl),
        "unrealized_pnl": float(final_snapshot.unrealized_pnl),
        "total_equity": float(final_snapshot.equity),
        "cash": float(final_snapshot.cash),
        "warnings": _dedupe(warnings),
        "validation_errors": list(validation["errors"]),
        "step_status": step_status,
        "manual_trade_ticket_count": len(tickets),
        "live_trading": False,
        "provider_health": validation["provider_health"],
        "artifacts": {
            "crypto_paper_forward_validation.json": str(validation_path),
            **ticket_artifacts,
        },
    }
    if close_result is not None:
        result["daily_close"] = {
            "ending_equity": close_result.performance.ending_equity,
            "total_pnl": close_result.performance.total_pnl,
            "artifacts": dict(close_result.artifacts_written),
        }
    if history_result is not None:
        result["history"] = history_result
    if evaluation_result is not None:
        result["evaluation"] = evaluation_result

    result_path = paper_forward_dir / "crypto_paper_forward_result.json"
    result_path.write_text(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    report_text = build_crypto_paper_forward_report(
        result=result,
        recommendations=engine_result.recommendations,
        execution_result=combined_execution,
        tickets=tickets,
    )
    report_path = paper_forward_dir / "crypto_paper_forward_report.md"
    report_path.write_text(report_text, encoding="utf-8")
    result["artifacts"]["crypto_paper_forward_result.json"] = str(result_path)
    result["artifacts"]["crypto_paper_forward_report.md"] = str(report_path)
    return result


def build_crypto_manual_trade_tickets(
    *,
    recommendations: RecommendationOutput,
    execution_result: CryptoPaperExecutionResult,
    engine_warnings: list[str],
    provider_warnings: list[str],
) -> list[dict[str, Any]]:
    tickets: list[dict[str, Any]] = []
    fills_by_symbol = {(fill.symbol, fill.side): fill for fill in execution_result.fills}
    for index, item in enumerate(recommendations.recommendations, start=1):
        if item.action != "BUY":
            continue
        fill = fills_by_symbol.get((item.asset_id, "BUY"))
        tickets.append(
            {
                "ticket_id": f"manual-ticket-{index:04d}",
                "symbol": item.asset_id,
                "action": item.action,
                "source": "BUY_SIGNAL",
                "paper_only": True,
                "manual_review_only": True,
                "not_auto_executed": True,
                "reason": item.reason,
                "reference_price": item.price_used,
                "stop_loss": item.extensions.get("stop_loss"),
                "take_profit": item.extensions.get("take_profit"),
                "max_notional": item.extensions.get("max_paper_notional", item.usd_target_effective),
                "risk_warnings": list(item.constraints),
                "provider_data_warnings": _dedupe(list(engine_warnings) + list(provider_warnings)),
                "provider": item.extensions.get("provider", item.price_source),
                "ticket_status": "FILLED_PAPER" if fill is not None else "SIGNAL_ONLY",
                "disclaimer": "Paper-only / manual-review only. Not auto-executed.",
            }
        )
    offset = len(tickets)
    for index, event in enumerate(execution_result.exit_events, start=1):
        tickets.append(
            {
                "ticket_id": f"manual-ticket-{offset + index:04d}",
                "symbol": event.symbol,
                "action": "SELL",
                "source": event.exit_reason,
                "paper_only": True,
                "manual_review_only": True,
                "not_auto_executed": True,
                "reason": f"Paper exit generated by {event.exit_reason}",
                "reference_price": event.fill_price,
                "stop_loss": event.metadata.get("stop_loss"),
                "take_profit": event.metadata.get("take_profit"),
                "max_notional": event.gross_notional,
                "risk_warnings": [event.exit_reason],
                "provider_data_warnings": _dedupe(list(provider_warnings)),
                "provider": event.source,
                "ticket_status": "EXIT_FILLED_PAPER",
                "disclaimer": "Paper-only / manual-review only. Not auto-executed.",
            }
        )
    return tickets


def write_crypto_manual_trade_tickets(
    *,
    output_dir: str | Path,
    tickets: list[dict[str, Any]],
) -> dict[str, str]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    json_path = root / "crypto_manual_trade_tickets.json"
    md_path = root / "crypto_manual_trade_tickets.md"
    json_path.write_text(json.dumps(tickets, sort_keys=True, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    md_path.write_text(build_crypto_manual_trade_tickets_report(tickets), encoding="utf-8")
    return {
        "crypto_manual_trade_tickets.json": str(json_path),
        "crypto_manual_trade_tickets.md": str(md_path),
    }


def build_crypto_manual_trade_tickets_report(tickets: list[dict[str, Any]]) -> str:
    lines = [
        "# Crypto Manual Trade Tickets",
        "",
        "Paper-only / manual-review only. These are not broker orders.",
        "",
    ]
    if not tickets:
        lines.append("- No manual trade tickets generated.")
        return "\n".join(lines) + "\n"
    for ticket in tickets:
        lines.extend(
            [
                f"## {ticket['ticket_id']}",
                f"- Symbol: {ticket['symbol']}",
                f"- Action: {ticket['action']}",
                f"- Source: {ticket['source']}",
                f"- Reason: {ticket['reason']}",
                f"- Reference price: {ticket['reference_price']}",
                f"- Stop loss: {ticket.get('stop_loss')}",
                f"- Take profit: {ticket.get('take_profit')}",
                f"- Max notional: {ticket.get('max_notional')}",
                f"- Status: {ticket['ticket_status']}",
                f"- Disclaimer: {ticket['disclaimer']}",
                "",
            ]
        )
    return "\n".join(lines) + "\n"


def build_crypto_paper_forward_report(
    *,
    result: dict[str, Any],
    recommendations: RecommendationOutput,
    execution_result: CryptoPaperExecutionResult,
    tickets: list[dict[str, Any]],
) -> str:
    lines = [
        "# Crypto Paper-Forward Daily Report",
        "",
        "## Executive Summary",
        f"- Run status: {result['status']}",
        f"- Paper-only status: {result['paper_only']}",
        f"- Candidate config used: {result['candidate_config_used']}",
        f"- Symbols evaluated: {', '.join(result.get('symbols_evaluated') or [])}",
        f"- Recommendations count: {result['recommendations_count']}",
        f"- Fills count: {result['fills_count']}",
        f"- Exits count: {result['exits_count']}",
        f"- Realized P&L: {result['realized_pnl']:.6f}",
        f"- Unrealized P&L: {result['unrealized_pnl']:.6f}",
        f"- Total equity: {result['total_equity']:.6f}",
        f"- Warnings: {len(result.get('warnings') or [])}",
        "",
        "## Signals",
    ]
    if not recommendations.recommendations:
        lines.append("- No signals.")
    else:
        for item in recommendations.recommendations:
            lines.append(
                f"- {item.asset_id}: {item.action} | reason={item.reason} | confidence={item.extensions.get('confidence')} | "
                f"stop_loss={item.extensions.get('stop_loss')} | take_profit={item.extensions.get('take_profit')}"
            )
    lines.extend(
        [
            "",
            "## Paper Execution",
            f"- Orders: {len(execution_result.accepted_orders) + len(execution_result.rejected_orders)}",
            f"- Fills: {len(execution_result.fills)}",
            f"- Rejected orders: {len(execution_result.rejected_orders)}",
            f"- Fees: {execution_result.portfolio_snapshot.fees_paid:.6f}",
            f"- Slippage: {sum(float(fill.slippage or 0.0) for fill in execution_result.fills):.6f}",
            "",
            "## Exits",
            f"- STOP_LOSS / TAKE_PROFIT events: {len(execution_result.exit_events)}",
            f"- Realized P&L: {execution_result.portfolio_snapshot.realized_pnl:.6f}",
            "",
            "## Portfolio",
            f"- Cash: {execution_result.portfolio_snapshot.cash:.6f}",
            f"- Positions: {len(execution_result.portfolio_snapshot.positions)}",
            f"- Equity: {execution_result.portfolio_snapshot.equity:.6f}",
            f"- P&L: {(execution_result.portfolio_snapshot.realized_pnl + execution_result.portfolio_snapshot.unrealized_pnl):.6f}",
            "",
            "## Strategy Evaluation",
        ]
    )
    evaluation = result.get("evaluation") or {}
    lines.extend(
        [
            f"- Closed trades: {evaluation.get('closed_trades_count', 0)}",
            f"- Open trades: {evaluation.get('open_trades_count', 0)}",
            f"- Win rate: {evaluation.get('win_rate')}",
            f"- Expectancy: {evaluation.get('expectancy')}",
            f"- Profit factor: {evaluation.get('profit_factor')}",
            f"- Fee drag: {evaluation.get('fee_drag_pct_of_gross_pnl')}",
            f"- Warnings: {evaluation.get('warnings', [])}",
            "",
            "## Manual Trade Tickets",
            f"- Tickets generated for human review only: {len(tickets)}",
            "",
            "## Warnings",
        ]
    )
    if not result.get("warnings"):
        lines.append("- None.")
    else:
        for warning in result["warnings"]:
            lines.append(f"- {warning}")
    return "\n".join(lines) + "\n"


def _evaluate_forward_exits(
    *,
    provider: Any,
    ledger: CryptoPaperLedger,
    strategy_config: dict[str, Any],
    as_of: datetime,
    warnings: list[str],
    latest_quotes: dict[str, Any] | None = None,
) -> list[CryptoPaperExitEvent]:
    candles_by_symbol: dict[str, Any] = {}
    for symbol in list(ledger.positions.keys()):
        try:
            candles_by_symbol[symbol] = provider.get_historical_bars(
                symbol=symbol,
                timeframe=str(strategy_config.get("timeframe", "5m")),
                limit=int(strategy_config.get("lookback_limit", 120)),
            )
        except Exception as exc:
            warnings.append(f"exit_candle_retrieval_failed:{symbol}:{exc}")
    return evaluate_crypto_exit_triggers(
        positions=list(ledger.positions.values()),
        candles_by_symbol=candles_by_symbol,
        as_of=as_of,
        config=ledger.config,
        latest_quotes=latest_quotes or {},
    )


def _merge_execution_results(
    first: CryptoPaperExecutionResult,
    second: CryptoPaperExecutionResult,
    final_snapshot: CryptoPaperPortfolioSnapshot,
) -> CryptoPaperExecutionResult:
    return CryptoPaperExecutionResult(
        accepted_orders=list(first.accepted_orders) + list(second.accepted_orders),
        rejected_orders=list(first.rejected_orders) + list(second.rejected_orders),
        fills=list(first.fills) + list(second.fills),
        portfolio_snapshot=final_snapshot,
        warnings=_dedupe(list(first.warnings) + list(second.warnings)),
        exit_events=list(first.exit_events) + list(second.exit_events),
        metadata={"paper_only": True, "live_trading": False},
    )


def _empty_execution_result(snapshot: CryptoPaperPortfolioSnapshot) -> CryptoPaperExecutionResult:
    return CryptoPaperExecutionResult(
        accepted_orders=[],
        rejected_orders=[],
        fills=[],
        portfolio_snapshot=snapshot,
        warnings=[],
        exit_events=[],
        metadata={"paper_only": True, "live_trading": False},
    )


def _load_forward_ledger(*, artifact_root: Path, config: CryptoPaperExecutionConfig) -> CryptoPaperLedger:
    ledger = CryptoPaperLedger(config)
    snapshot_path = artifact_root / "crypto_paper_snapshot.json"
    positions_path = artifact_root / "crypto_paper_positions.json"
    if snapshot_path.exists():
        try:
            payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                ledger.cash = float(payload.get("cash") or ledger.cash)
                ledger.fees_paid = float(payload.get("fees_paid") or 0.0)
                ledger.realized_pnl = float(payload.get("realized_pnl") or 0.0)
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
            symbol=str(payload.get("symbol") or "").upper(),
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


def _write_execution_artifacts(*, artifact_root: Path, result: CryptoPaperExecutionResult) -> list[str]:
    """Persist execution artifacts cumulatively. Returns merge warnings."""

    artifact_root.mkdir(parents=True, exist_ok=True)
    current_orders = [order.to_dict() for order in result.accepted_orders + result.rejected_orders]
    current_fills = [fill.to_dict() for fill in result.fills]
    current_exits = [event.to_dict() for event in result.exit_events]

    merged_orders, order_warnings = _merge_cumulative_records(
        path=artifact_root / "crypto_paper_orders.json",
        current=current_orders,
        id_key="order_id",
        sort_keys=("created_at", "order_id"),
    )
    merged_fills, fill_warnings = _merge_cumulative_records(
        path=artifact_root / "crypto_paper_fills.json",
        current=current_fills,
        id_key="fill_id",
        sort_keys=("filled_at", "fill_id"),
    )
    merged_exits, exit_warnings = _merge_cumulative_records(
        path=artifact_root / "crypto_paper_exit_events.json",
        current=current_exits,
        id_key="exit_id",
        sort_keys=("exited_at", "exit_id"),
    )

    payloads = {
        "crypto_paper_orders.json": merged_orders,
        "crypto_paper_fills.json": merged_fills,
        "crypto_paper_exit_events.json": merged_exits,
        "crypto_paper_positions.json": [position.to_dict() for position in result.portfolio_snapshot.positions],
        "crypto_paper_snapshot.json": result.portfolio_snapshot.to_dict(),
        "crypto_paper_execution_result.json": result.to_dict(),
    }
    for filename, payload in payloads.items():
        (artifact_root / filename).write_text(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    return _dedupe(list(order_warnings) + list(fill_warnings) + list(exit_warnings))


def _merge_cumulative_records(
    *,
    path: Path,
    current: list[dict[str, Any]],
    id_key: str,
    sort_keys: tuple[str, ...],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Merge current-run records with persisted cumulative records.

    - If a stable ``id_key`` exists and the content is identical to a record
      already accumulated under that id, the duplicate is dropped.
    - If a stable ``id_key`` collides but the content differs, BOTH records
      are preserved and a warning is emitted. This avoids silently losing
      historical fills/orders/exits when run-local IDs collide across runs.
    - Items without an id are deduplicated by canonical JSON content so reruns
      do not duplicate identical no-id rows.
    - Output is deterministically sorted by ``sort_keys`` with a JSON-content
      tiebreaker so equal sort tuples produce a stable order.
    - Existing data is preserved when the current run produced zero items.
    - Malformed/empty existing files are treated as empty (no crash).
    """

    existing: list[dict[str, Any]] = []
    if path.exists():
        try:
            text = path.read_text(encoding="utf-8").strip()
            if text:
                payload = json.loads(text)
                if isinstance(payload, list):
                    existing = [item for item in payload if isinstance(item, dict)]
        except Exception:
            existing = []

    by_id_records: dict[str, list[dict[str, Any]]] = {}
    no_id_records: list[dict[str, Any]] = []
    seen_no_id_keys: set[str] = set()
    warnings: list[str] = []

    def _content_key(item: dict[str, Any]) -> str:
        try:
            return json.dumps(item, sort_keys=True, ensure_ascii=False, default=str)
        except Exception:
            return repr(item)

    for source in (existing, current):
        for item in source:
            if not isinstance(item, dict):
                continue
            identifier = item.get(id_key)
            if isinstance(identifier, str) and identifier:
                bucket = by_id_records.setdefault(identifier, [])
                item_key = _content_key(item)
                duplicate = any(_content_key(existing_item) == item_key for existing_item in bucket)
                if duplicate:
                    continue
                bucket.append(item)
                if len(bucket) > 1:
                    warnings.append(
                        f"id_collision_with_diff_content:{id_key}={identifier}"
                    )
                continue
            content_key = _content_key(item)
            if content_key in seen_no_id_keys:
                continue
            seen_no_id_keys.add(content_key)
            no_id_records.append(item)

    merged: list[dict[str, Any]] = []
    for bucket in by_id_records.values():
        merged.extend(bucket)
    merged.extend(no_id_records)

    def _sort_key(record: dict[str, Any]) -> tuple:
        primary = tuple(("" if record.get(key) is None else str(record.get(key))) for key in sort_keys)
        return primary + (_content_key(record),)

    merged.sort(key=_sort_key)
    return merged, _dedupe(warnings)


def _empty_recommendations(context: EngineContext) -> RecommendationOutput:
    return RecommendationOutput.build(
        run_id=context.run_id,
        horizon="INTRADAY",
        asof_date=context.metadata.get("asof_date") or context.as_of.strftime("%Y-%m-%d"),
        policy_id="crypto_paper_forward",
        policy_version="1",
        constraints=[],
        sizing_rule="crypto.paper.fixed_notional",
        recommendations=[],
        cash_summary={},
        cash_policy="engine.noop",
        execution_date=context.metadata.get("execution_date"),
        execution_hour=context.metadata.get("execution_hour"),
    )


def _empty_engine_result(context: EngineContext):
    return type(
        "ForwardEngineResult",
        (),
        {
            "recommendations": _empty_recommendations(context),
            "diagnostics": type("ForwardDiagnostics", (), {"warnings": []})(),
        },
    )()


def _normalize_prices_bundle(bundle: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    payload = dict(bundle or {})
    if "candles" in payload or "quotes" in payload:
        raw_quotes = dict(payload.get("quotes") or {})
        raw_candles = dict(payload.get("candles") or {})
    else:
        if all(isinstance(value, list) for value in payload.values()):
            raw_quotes = {}
            raw_candles = payload
        else:
            raw_quotes = payload
            raw_candles = {}
    quotes: dict[str, dict[str, Any]] = {}
    candles: dict[str, list[dict[str, Any]]] = {}
    for symbol, rows in raw_candles.items():
        normalized_symbol = str(symbol).upper()
        normalized_rows: list[dict[str, Any]] = []
        for row in list(rows or []):
            if not isinstance(row, dict):
                continue
            parsed = pd.Timestamp(row.get("timestamp") or row.get("date"))
            if parsed.tzinfo is not None:
                parsed = parsed.tz_convert("UTC").tz_localize(None)
            timestamp = parsed.to_pydatetime()
            normalized_rows.append(
                {
                    "date": timestamp,
                    "ticker": normalized_symbol,
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("volume") or 0.0),
                }
            )
        normalized_rows.sort(key=lambda item: item["date"])
        candles[normalized_symbol] = normalized_rows
        if normalized_rows and normalized_symbol not in raw_quotes:
            close = float(normalized_rows[-1]["close"])
            quotes[normalized_symbol] = {
                "provider": "static_crypto_forward",
                "symbol": normalized_symbol,
                "last_price": close,
                "ask": close,
                "bid": close,
            }
    for symbol, quote in raw_quotes.items():
        normalized_symbol = str(symbol).upper()
        if isinstance(quote, dict):
            last_price = quote.get("last_price", quote.get("ask", quote.get("bid")))
            quotes[normalized_symbol] = {
                "provider": "static_crypto_forward",
                "symbol": normalized_symbol,
                "last_price": float(last_price) if last_price is not None else None,
                "ask": float(quote["ask"]) if quote.get("ask") is not None else (float(last_price) if last_price is not None else None),
                "bid": float(quote["bid"]) if quote.get("bid") is not None else (float(last_price) if last_price is not None else None),
            }
        else:
            value = float(quote)
            quotes[normalized_symbol] = {
                "provider": "static_crypto_forward",
                "symbol": normalized_symbol,
                "last_price": value,
                "ask": value,
                "bid": value,
            }
    return quotes, candles


def _has_sensitive_keys(payload: Any, names: set[str]) -> bool:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if str(key).lower() in names:
                return True
            if _has_sensitive_keys(value, names):
                return True
    elif isinstance(payload, list):
        for item in payload:
            if _has_sensitive_keys(item, names):
                return True
    return False


def _safe_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_as_of(value: datetime | str | None) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
    if value:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            return parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    return datetime.utcnow().replace(tzinfo=None)


def _flag(name: str) -> bool:
    value = str(os.getenv(name) or "").strip().lower()
    return value in {"1", "true", "yes", "y", "si", "s"}


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


def _build_failed_report(result: dict[str, Any]) -> str:
    lines = [
        "# Crypto Paper-Forward Daily Report",
        "",
        "## Executive Summary",
        f"- Run status: {result['status']}",
        "- Paper-only status: true",
        f"- Candidate config used: {result['candidate_config_used']}",
        "",
        "## Warnings",
    ]
    for warning in list(result.get("warnings") or []):
        lines.append(f"- {warning}")
    lines.extend(["", "## Validation Errors"])
    for error in list(result.get("validation_errors") or []):
        lines.append(f"- {error}")
    return "\n".join(lines) + "\n"
