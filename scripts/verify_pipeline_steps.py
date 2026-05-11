import argparse
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from src.execution.process.normalize_prices import normalize_prices
import src.execution.process.process_indicators as process_indicators
from src.pipeline.feature_engineering import combine_features
from src.backtest.backtest_strategy import (
    FEATURES_BASE,
    get_latest_features_path,
    load_features_range,
)
from src.utils.execution_context import get_execution_date, get_execution_hour


def _print_status(step: str, ok: bool, details: str = "") -> None:
    status = "OK" if ok else "WARN"
    print(f"[{status}] {step} {details}".strip())


def _pick_ticker(normalized_base: Path) -> str:
    files = sorted(normalized_base.glob("*.parquet"))
    return files[0].stem if files else ""


def verify_normalize_prices(date: datetime, hour: str) -> None:
    log_path = normalize_prices(date, hour)
    normalized_base = Path("data/raw/prices/normalized")
    ok = normalized_base.exists() and any(normalized_base.glob("*.parquet"))
    _print_status("normalize_prices", ok, f"log={log_path}" if ok else "no normalized files")


def verify_process_indicators(date: datetime, hour: str, lookback_days: int) -> None:
    normalized_base = Path("data/raw/prices/normalized")
    ticker = _pick_ticker(normalized_base)
    if not ticker:
        _print_status("process_indicators", False, "no normalized tickers")
        return
    process_indicators.calculate_indicators(ticker, date, hour, lookback_days)
    out_dir = Path("data/processed/indicadores") / f"{date.year:04d}" / f"{date.month:02d}" / f"{date.day:02d}" / hour
    out_path = out_dir / f"{ticker}.parquet"
    _print_status("process_indicators", out_path.exists(), f"ticker={ticker} path={out_path}")


def verify_feature_engineering(date: datetime, hour: str) -> None:
    sentiment_path = Path("data/processed_daily/sentiment_daily.parquet")
    if sentiment_path.exists():
        _print_status("feature_engineering", False, "sentiment_daily exists; skip missing-sentiment check")
        return
    try:
        combine_features(date, hour)
        _print_status("feature_engineering", True, "ran without sentiment_daily")
    except Exception as exc:
        _print_status("feature_engineering", False, f"error={exc}")


def verify_backtest_lookback() -> None:
    try:
        latest_path = get_latest_features_path(FEATURES_BASE)
        end_date = datetime.strptime("-".join(latest_path.parts[-4:-1]), "%Y-%m-%d")
        start_date = end_date - timedelta(days=2)
        df = load_features_range(start_date, end_date)
        ok = not df.empty and df["ticker"].nunique() > 0
        _print_status("backtest_lookback", ok, f"rows={len(df)}")
    except Exception as exc:
        _print_status("backtest_lookback", False, f"error={exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verifica pasos clave del pipeline.")
    parser.add_argument("--date", type=str, help="YYYY-MM-DD")
    parser.add_argument("--hour", type=str, help="HHMM")
    parser.add_argument("--lookback-days", type=int, default=400)
    args = parser.parse_args()

    date = get_execution_date(args.date)
    hour = get_execution_hour(args.hour)

    verify_normalize_prices(date, hour)
    verify_process_indicators(date, hour, args.lookback_days)
    verify_feature_engineering(date, hour)
    verify_backtest_lookback()


if __name__ == "__main__":
    main()
