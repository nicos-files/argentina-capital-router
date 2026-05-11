from __future__ import annotations

import argparse
import json
from typing import Any, Dict

from src.decision_intel.integrations.quant_trading_bot_adapter import build_decision_intel_artifacts
from src.run import parse_args as parse_run_args
from src.run import run_pipeline
from src.tools.close_paper_day import close_paper_day
from src.tools.notify_telegram import notify_telegram
from src.tools.run_free import run_free
from src.tools.run_all import run_all


def _run_pipeline_from_args(args: argparse.Namespace) -> Dict[str, Any]:
    run_args = parse_run_args(argv=[])
    if args.date:
        run_args.date = args.date
    if args.hour:
        run_args.hour = args.hour
    if args.no_etl:
        run_args.no_etl = True
    if args.only_agent:
        run_args.only_agent = True
    for attr in (
        "skip_alpha",
        "skip_fetch_prices",
        "skip_fundamentals",
        "skip_relevance",
        "skip_sentiment",
        "force_process_prices",
        "skip_process_prices",
        "force_fundamentals",
        "force_relevance",
        "force_sentiment",
    ):
        if hasattr(args, attr):
            setattr(run_args, attr, getattr(args, attr))

    result = run_pipeline(run_args)
    if isinstance(result, dict):
        return {"date": result.get("date", run_args.date), "hour": result.get("hour", run_args.hour)}
    return {"date": run_args.date, "hour": run_args.hour}


def _run_decision_intel_from_args(args: argparse.Namespace, pipeline_result: Dict[str, Any] | None = None) -> None:
    date = args.date or (pipeline_result or {}).get("date")
    hour = args.hour or (pipeline_result or {}).get("hour")
    build_decision_intel_artifacts(
        run_id=args.run_id,
        base_path=args.runs_base_path,
        final_decision_path=args.final_decision_path,
        backtest_summary_path=args.backtest_summary_path,
        config_snapshot_path=args.config_snapshot_path,
        weights_json=args.weights_json,
        weights_file=args.weights_file,
        date=date,
        hour=hour,
        emit_recommendations=args.emit_recommendations,
    )


def _add_pipeline_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--date", type=str, help="Fecha en formato YYYY-MM-DD")
    parser.add_argument("--hour", type=str, help="Hora en formato HHMM")
    parser.add_argument("--no-etl", action="store_true", help="Saltear ETL")
    parser.add_argument("--only-agent", action="store_true", help="Ejecutar solo agentes")
    parser.add_argument("--skip-alpha", action="store_true")
    parser.add_argument("--skip-fetch_prices", action="store_true", help="Saltear ingesta de precios")
    parser.add_argument("--skip-fundamentals", action="store_true")
    parser.add_argument("--skip-relevance", action="store_true")
    parser.add_argument("--skip-sentiment", action="store_true")
    parser.add_argument("--force-process_prices", action="store_true", help="Forzar procesamiento de precios incluso sin nuevos datos")
    parser.add_argument("--skip-process_prices", action="store_true", help="Saltear procesamiento de precios")
    parser.add_argument("--force-fundamentals", action="store_true")
    parser.add_argument("--force-relevance", action="store_true")
    parser.add_argument("--force-sentiment", action="store_true")


def _add_decision_intel_args(parser: argparse.ArgumentParser, include_date_hour: bool = True) -> None:
    parser.add_argument("--run-id", type=str, help="Override run_id for Decision Intel")
    parser.add_argument("--runs-base-path", type=str, default="runs")
    if include_date_hour:
        parser.add_argument("--date", type=str, help="Fecha en formato YYYY-MM-DD")
        parser.add_argument("--hour", type=str, help="Hora en formato HHMM")
    parser.add_argument("--final-decision-path", type=str, help="Override path to final_decision.json")
    parser.add_argument("--backtest-summary-path", type=str, help="Override path to backtest_summary.json")
    parser.add_argument("--config-snapshot-path", type=str, help="Override config snapshot path for manifest")
    parser.add_argument("--weights-json", type=str, help="Portfolio weights as JSON string")
    parser.add_argument("--weights-file", type=str, help="Portfolio weights JSON file path")
    parser.add_argument("--emit-recommendations", action="store_true", help="Emit recommendation outputs")


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError("Expected boolean value (true/false)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Unified quant-trading-bot CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    pipeline_parser = subparsers.add_parser("pipeline", help="Run pipeline only")
    _add_pipeline_args(pipeline_parser)

    decision_intel_parser = subparsers.add_parser("decision-intel", help="Run Decision Intel adapter only")
    _add_decision_intel_args(decision_intel_parser, include_date_hour=True)

    run_parser = subparsers.add_parser("run", help="Run full pipeline + Decision Intel artifacts")
    _add_pipeline_args(run_parser)
    _add_decision_intel_args(run_parser, include_date_hour=False)

    run_all_parser = subparsers.add_parser("run-all", help="Run end-to-end pipeline + recommendations")
    run_all_parser.add_argument("--date", type=str, required=True, help="Fecha en formato YYYY-MM-DD")
    run_all_parser.add_argument("--hour", type=str, required=True, help="Hora en formato HHMM")
    run_all_parser.add_argument("--mode", choices=["live", "offline"], default="offline")
    run_all_parser.add_argument("--timeout-sec", type=int, default=600)
    run_all_parser.add_argument("--emit-recommendations", action="store_true", default=True)
    run_all_parser.add_argument("--skip-train", action="store_true")
    run_all_parser.add_argument("--skip-backtest", action="store_true")
    run_all_parser.add_argument("--skip-simulate", action="store_true")
    run_all_parser.add_argument("--dry-run", action="store_true")
    run_all_parser.add_argument(
        "--skip-live-ingest",
        action="store_true",
        help="Skip live ingest/sentiment/price steps (paper trading without external deps)",
    )
    run_all_parser.add_argument("--execute", action="store_true", help="Execute orders from execution.plan")
    run_all_parser.add_argument(
        "--paper",
        type=_parse_bool,
        nargs="?",
        const="true",
        default=True,
        help="Paper trading mode (true/false)",
    )
    run_all_parser.add_argument("--kill-switch", type=str, help="Override kill switch file path")

    run_free_parser = subparsers.add_parser("run-free", help="Run the free-only stabilization workflow")
    run_free_parser.add_argument("--date", type=str, required=True, help="Fecha en formato YYYY-MM-DD")
    run_free_parser.add_argument("--hour", type=str, required=True, help="Hora en formato HHMM")
    run_free_parser.add_argument("--price-profile", type=str, default="free-core")
    run_free_parser.add_argument("--fundamentals-profile", type=str, default="free-portfolio")
    run_free_parser.add_argument("--start-date", type=str, help="YYYY-MM-DD")
    run_free_parser.add_argument("--timeout-sec", type=int, default=900)
    run_free_parser.add_argument("--skip-train", action="store_true")
    run_free_parser.add_argument("--skip-fundamentals", action="store_true")
    run_free_parser.add_argument("--execute", action="store_true")
    run_free_parser.add_argument(
        "--paper",
        type=_parse_bool,
        nargs="?",
        const="true",
        default=True,
        help="Paper trading mode (true/false)",
    )
    run_free_parser.add_argument("--notify-telegram", action="store_true")
    run_free_parser.add_argument("--telegram-bot-token", type=str)
    run_free_parser.add_argument("--telegram-chat-id", type=str)

    close_parser = subparsers.add_parser("close-paper-day", help="Summarize paper trading day PnL for a run")
    close_parser.add_argument("--run-id", type=str, required=True)
    close_parser.add_argument("--runs-base-path", type=str, default="runs")
    close_parser.add_argument("--mark-date", type=str, help="Mark portfolio with features close from YYYY-MM-DD")

    telegram_parser = subparsers.add_parser("notify-telegram", help="Send recommendation summary to Telegram")
    telegram_parser.add_argument("--run-id", type=str, required=True)
    telegram_parser.add_argument("--runs-base-path", type=str, default="runs")
    telegram_parser.add_argument("--bot-token", type=str)
    telegram_parser.add_argument("--chat-id", type=str)
    telegram_parser.add_argument("--include-close", action="store_true")
    telegram_parser.add_argument("--timeout-sec", type=int, default=20)

    args = parser.parse_args()

    if args.command == "pipeline":
        summary = _run_pipeline_from_args(args)
        print(json.dumps(summary, sort_keys=True, separators=(",", ":"), ensure_ascii=False))
    elif args.command == "decision-intel":
        _run_decision_intel_from_args(args)
    elif args.command == "run":
        summary = _run_pipeline_from_args(args)
        _run_decision_intel_from_args(args, pipeline_result=summary)
    elif args.command == "run-all":
        run_all(
            date=args.date,
            hour=args.hour,
            mode=args.mode,
            timeout_sec=args.timeout_sec,
            emit_recommendations=args.emit_recommendations,
            skip_train=args.skip_train,
            skip_backtest=args.skip_backtest,
            skip_simulate=args.skip_simulate,
            dry_run=args.dry_run,
            skip_live_ingest=args.skip_live_ingest,
            execute=args.execute,
            paper=args.paper,
            kill_switch=args.kill_switch,
        )
    elif args.command == "run-free":
        run_free(
            date=args.date,
            hour=args.hour,
            price_profile=args.price_profile,
            fundamentals_profile=args.fundamentals_profile,
            start_date=args.start_date,
            timeout_sec=args.timeout_sec,
            skip_train=args.skip_train,
            skip_fundamentals=args.skip_fundamentals,
            execute=args.execute,
            paper=args.paper,
            notify_telegram_enabled=args.notify_telegram,
            telegram_bot_token=args.telegram_bot_token,
            telegram_chat_id=args.telegram_chat_id,
        )
    elif args.command == "close-paper-day":
        close_paper_day(
            run_id=args.run_id,
            base_path=args.runs_base_path,
            mark_date=args.mark_date,
        )
    elif args.command == "notify-telegram":
        summary = notify_telegram(
            run_id=args.run_id,
            base_path=args.runs_base_path,
            bot_token=args.bot_token,
            chat_id=args.chat_id,
            include_close=args.include_close,
            timeout_sec=args.timeout_sec,
        )
        print(json.dumps(summary, sort_keys=True, separators=(",", ":"), ensure_ascii=False))


if __name__ == "__main__":
    main()
