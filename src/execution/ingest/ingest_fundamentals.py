import os
import requests
import pandas as pd
import argparse
import hashlib
import time
from pathlib import Path
from datetime import datetime
from typing import Optional
from src.asset_universe import iter_assets
from src.source_profiles import filter_free_fundamentals_assets, get_profile_asset_ids
from src.utils.execution_context import (
    get_execution_date,
    get_execution_hour,
    ensure_date_dir
)

def hash_df(df: pd.DataFrame) -> str:
    return hashlib.md5(pd.util.hash_pandas_object(df, index=True).values).hexdigest()

ALPHA_VANTAGE_API_KEY = "TGES6LEV1PPQSVIB"
FINNHUB_API_KEY = "d2qr8j1r01qluccpn6agd2qr8j1r01qluccpn6b0"
ROOT = Path(__file__).resolve().parents[3] 
RAW_PATH = ROOT / "data" / "raw"
FUNDAMENTALS_DIR = RAW_PATH / "fundamentals"

def save_raw_data_if_changed(df: pd.DataFrame, origen: str, ticker: str, date: datetime, hour: Optional[str]) -> bool:
    target_dir = ensure_date_dir(FUNDAMENTALS_DIR / origen / ticker, date, hour)
    new_path = target_dir / f"{ticker}.parquet"

    # Buscar archivo anterior
    prev_files = sorted(
        (FUNDAMENTALS_DIR / origen / ticker).rglob(f"{ticker}.parquet"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )

    if prev_files:
        try:
            df_prev = pd.read_parquet(prev_files[0])
            if hash_df(df_prev) == hash_df(df):
                print(f" Sin cambios en {origen} para {ticker}, no se guarda.")
                return False
        except Exception as e:
            print(f" Error al comparar con archivo anterior: {e}")

    df.to_parquet(new_path, index=False)
    print(f" Guardado: {new_path}")
    return True

def fetch_fundamentals_alpha(ticker: str) -> Optional[pd.DataFrame]:
    print(f" Alpha Vantage: {ticker}")
    url = "https://www.alphavantage.co/query"
    params = {
        "function": "OVERVIEW",
        "symbol": ticker,
        "apikey": ALPHA_VANTAGE_API_KEY
    }

    try:
        response = requests.get(url, params=params, timeout=30)
        data = response.json()
        if not data or "Symbol" not in data:
            print(f"No data from Alpha Vantage for {ticker}")
            return None
        df = pd.DataFrame([data])
        df["source"] = "alpha_vantage"
        return df
    except Exception as e:
        print(f" Error Alpha Vantage: {e}")
        return None

def fetch_fundamentals_finnhub(ticker: str) -> Optional[pd.DataFrame]:
    print(f" Finnhub: {ticker}")
    url = "https://finnhub.io/api/v1/stock/metric"
    params = {
        "symbol": ticker,
        "metric": "all",
        "token": FINNHUB_API_KEY
    }

    try:
        response = requests.get(url, params=params, timeout=30)
        data = response.json()
        if "metric" not in data:
            print(f" No data from Finnhub for {ticker}")
            return None
        df = pd.DataFrame([data["metric"]])
        df["source"] = "finnhub"
        return df
    except Exception as e:
        print(f" Error Finnhub: {e}")
        return None

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, help="Fecha en formato YYYY-MM-DD")
    parser.add_argument("--hour", type=str, help="Hora en formato HHMM")
    parser.add_argument("--asset-id", action="append", dest="asset_ids")
    parser.add_argument("--profile", type=str, help="Universe profile, e.g. free-core/free-portfolio")
    parser.add_argument("--free-only", action="store_true", help="Limit to assets with viable free fundamentals today")
    parser.add_argument("--max-assets", type=int, help="Cap selected assets after filters")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    date = get_execution_date(args.date)
    hour = get_execution_hour(args.hour)

    selected_asset_ids = args.asset_ids or get_profile_asset_ids(args.profile)
    universe = iter_assets(enabled_only=True, asset_ids=selected_asset_ids, markets=["US"], asset_classes=["EQUITY"])
    if args.free_only:
        universe = filter_free_fundamentals_assets(universe)
    if args.max_assets and args.max_assets > 0:
        universe = universe[: args.max_assets]

    print(f"[FUND] universo seleccionado={len(universe)}")
    for asset in universe:
        ticker = asset.asset_id.replace(".US", "")
        df_alpha = fetch_fundamentals_alpha(ticker)
        df_finnhub = fetch_fundamentals_finnhub(ticker)

        if df_alpha is not None:
            print(f"\n Preview Alpha Vantage: {ticker}")
            print(df_alpha.head())
            save_raw_data_if_changed(df_alpha, origen="alphaV", ticker=ticker, date=date, hour=hour)
        else:
            print(" No data from Alpha Vantage")

        if df_finnhub is not None:
            print(f"\n Preview Finnhub: {ticker}")
            print(df_finnhub.head())
            save_raw_data_if_changed(df_finnhub, origen="finnhub", ticker=ticker, date=date, hour=hour)
        else:
            print(" No data from Finnhub")
        time.sleep(1.1)
