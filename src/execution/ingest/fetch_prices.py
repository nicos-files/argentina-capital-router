import argparse
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from src.asset_universe import AssetDefinition, iter_assets
from src.market_data.providers import (
    ALPHAV_PROVIDER,
    YFINANCE_PROVIDER,
    build_default_price_providers,
    fetch_price_history_with_fallback,
)
from src.source_profiles import filter_free_price_assets, get_profile_asset_ids
from src.utils.execution_context import (
    get_execution_date,
    get_execution_hour,
    ensure_date_dir
)

START_DATE = "2018-01-01"
FUENTE = "prices"
ROOT = Path(__file__).resolve().parents[3] 
RAW_PATH = ROOT / "data" / "raw"
REQUIRED_COLS = ["open", "high", "low", "close", "volume"]

def get_latest_raw_date(ticker: str) -> Optional[pd.Timestamp]:
    files = []
    for provider in (YFINANCE_PROVIDER, ALPHAV_PROVIDER):
        provider_base = RAW_PATH / FUENTE / provider / ticker
        if provider_base.exists():
            files.extend(provider_base.rglob("*.parquet"))
    if not files:
        legacy_base = RAW_PATH / FUENTE / ticker
        if legacy_base.exists():
            files.extend(legacy_base.rglob("*.parquet"))
    if not files:
        return None
    latest = max(files, key=lambda p: p.stat().st_mtime)
    try:
        df = pd.read_parquet(latest)
        if "date" in df.columns:
            return pd.to_datetime(df["date"], errors="coerce").max()
        if df.index.name and isinstance(df.index, pd.DatetimeIndex):
            return df.index.max()
    except Exception:
        return None
    return None

def save_raw_data(df: pd.DataFrame, fuente: str, provider: str, ticker: str, date: datetime, hour: Optional[str]):
    target_dir = ensure_date_dir(
        base=RAW_PATH / fuente / provider / ticker,
        date=date,
        hour=hour
    )
    path = target_dir / f"{fuente}_{ticker}.parquet"
    df.to_parquet(path)
    print(f"[FETCH] guardado {ticker} -> {path}")

def fetch_price_data(asset: AssetDefinition) -> tuple[str, Optional[pd.DataFrame]]:
    latest_dt = get_latest_raw_date(asset.asset_id)
    start_date = START_DATE
    if latest_dt is not None and pd.notna(latest_dt):
        start_date = (latest_dt + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        if pd.Timestamp(start_date) >= pd.Timestamp((datetime.now(timezone.utc).date() + timedelta(days=1)).strftime("%Y-%m-%d")):
            print(f"[FETCH] {asset.asset_id}: sin nuevos datos desde {latest_dt.date()}")
            return YFINANCE_PROVIDER, None
    return fetch_price_history_with_fallback(
        asset=asset,
        start_date=start_date,
        providers=build_default_price_providers(),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, help="Fecha en formato YYYY-MM-DD")
    parser.add_argument("--hour", type=str, help="Hora en formato HHMM")
    parser.add_argument("--asset-class", action="append", dest="asset_classes")
    parser.add_argument("--market", action="append", dest="markets")
    parser.add_argument("--asset-id", action="append", dest="asset_ids")
    parser.add_argument("--profile", type=str, help="Universe profile, e.g. free-core/free-us-small/free-forex")
    parser.add_argument("--free-only", action="store_true", help="Limit to assets with a viable free price source today")
    parser.add_argument("--max-assets", type=int, help="Cap selected assets after filters")
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args()

    date = get_execution_date(args.date)
    hour = get_execution_hour(args.hour)

    selected_asset_ids = args.asset_ids or get_profile_asset_ids(args.profile)
    universe = iter_assets(
        enabled_only=True,
        asset_classes=args.asset_classes,
        markets=args.markets,
        asset_ids=selected_asset_ids,
    )
    if args.free_only:
        universe = filter_free_price_assets(universe)
    if args.max_assets and args.max_assets > 0:
        universe = universe[: args.max_assets]
    print(f"[FETCH] universo seleccionado={len(universe)}")

    for asset in universe:
        provider, df = fetch_price_data(asset)
        if df is not None:
            save_raw_data(df, fuente=FUENTE, provider=provider, ticker=asset.asset_id, date=date, hour=hour)
        if provider == ALPHAV_PROVIDER:
            time.sleep(1.2)
        else:
            time.sleep(0.2)
