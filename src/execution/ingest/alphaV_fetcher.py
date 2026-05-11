import requests
import pandas as pd
import os
import argparse
from pathlib import Path
from typing import Optional
from src.utils.execution_context import (
    get_execution_date,
    get_execution_hour,
    ensure_date_dir
)

# Tu clave API de Alpha Vantage
ALPHA_VANTAGE_API_KEY = "TGES6LEV1PPQSVIB"
ROOT = Path(__file__).resolve().parents[3] 
RAW_PATH = ROOT / "data" / "raw"/"prices"

def has_prior_data(ticker: str) -> bool:
    base = RAW_PATH / "alphaV" / ticker
    return base.exists() and any(base.rglob("*.parquet"))

def fetch_from_alpha_vantage(ticker: str) -> Optional[pd.DataFrame]:
    print(f"Alpha Vantage: {ticker}")
    symbol = ticker.replace(".US", "").replace(".BA", "")

    url = "https://www.alphavantage.co/query"
    #outputsize = "compact" if has_prior_data(ticker) else "full" --REVISAR A FUTURO SI PAGAMOS SUSCRIPCION
    outputsize = "compact"
    params = {
        "function": "TIME_SERIES_DAILY",
        "symbol": symbol,
        "outputsize": outputsize,
        "apikey": ALPHA_VANTAGE_API_KEY
    }

    try:
        response = requests.get(url, params=params)
        data = response.json()

        if "Time Series (Daily)" not in data:
            print(f"No data found for {symbol}. Mensaje: {data.get('Information', 'Sin información')}")
            return None

        ts_data = data["Time Series (Daily)"]
        df = pd.DataFrame.from_dict(ts_data, orient="index")
        df.index = pd.to_datetime(df.index)
        df = df.sort_index()

        df = df.rename(columns={
            "1. open": "open",
            "2. high": "high",
            "3. low": "low",
            "4. close": "close",
            "5. volume": "volume"
        })

        df = df[["open", "high", "low", "close", "volume"]].astype(float)
        return df

    except Exception as e:
        print(f" Error Alpha Vantage: {e}")
        return None

def save_raw_data(df: pd.DataFrame, fuente: str, ticker: str, date, hour: Optional[str]):
    """
    Guarda un DataFrame en data/raw/<fuente>/<ticker>/YYYY/MM/DD/HHMM/<archivo>.parquet
    """
    target_dir = ensure_date_dir(
    base=RAW_PATH / fuente / ticker,
    date=date,
    hour=hour
    )


    path = target_dir / f"{fuente}_{ticker}.parquet"
    df.to_parquet(path)
    print(f" Guardado: {path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, help="Fecha en formato YYYY-MM-DD")
    parser.add_argument("--hour", type=str, help="Hora en formato HHMM")
    args = parser.parse_args()

    date = get_execution_date(args.date)
    hour = get_execution_hour(args.hour)

    tickers = ["AAPL.US", "TSLA.US", "GOOGL.US", "MSFT.US", "META.US", "NVDA.US", "AMZN.US"]
    for ticker in tickers:
        df = fetch_from_alpha_vantage(ticker)
        if df is not None and not df.empty:
            save_raw_data(df, fuente="alphaV", ticker=ticker, date=date, hour=hour)
