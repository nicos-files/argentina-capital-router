import pandas as pd
import argparse
from pathlib import Path
from src.utils.execution_context import (
    get_execution_date,
    get_execution_hour,
    ensure_date_dir
)

ROOT = Path(__file__).resolve().parents[3]
NORMALIZED_BASE = ROOT / "data" / "raw" / "prices" / "normalized"
INDICADORES_BASE = ROOT / "data" / "processed" / "indicadores"

REQUIRED_COLS = ["open", "high", "low", "close", "volume"]
INDICATOR_COLS = [
    "SMA_20",
    "EMA_20",
    "daily_return",
    "volatility",
    "volume_avg",
    "RSI",
    "MACD",
    "MACD_signal",
    "bollinger_upper",
    "bollinger_lower",
    "bollinger_width",
]


def _load_normalized_prices(ticker: str) -> pd.DataFrame:
    path = NORMALIZED_BASE / f"{ticker}.parquet"
    if not path.exists():
        print(f" No se encontro archivo normalizado para {ticker}: {path}")
        return pd.DataFrame()
    df = pd.read_parquet(path)
    if "date" in df.columns:
        dates = pd.to_datetime(df["date"], errors="coerce")
        if getattr(dates.dt, "tz", None) is not None:
            dates = dates.dt.tz_localize(None)
        df["date"] = dates.dt.normalize()
        df = df.set_index("date", drop=True)
    elif isinstance(df.index, pd.DatetimeIndex):
        dates = pd.to_datetime(df.index, errors="coerce")
        if getattr(dates.tz, "zone", None) is not None:
            dates = dates.tz_localize(None)
        df.index = dates.normalize()
    else:
        print(f" {ticker}: no hay columna date ni indice datetime en {path}")
        return pd.DataFrame()
    return df


def calculate_indicators(ticker: str, date, hour: str, lookback_days: int):
    df = _load_normalized_prices(ticker)
    if df.empty:
        return None

    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        print(f" {ticker}: faltan columnas {missing} en normalizados, se omite.")
        return None

    run_date = pd.to_datetime(date).normalize()
    start_date = run_date - pd.Timedelta(days=lookback_days)
    df = df.loc[(df.index >= start_date) & (df.index <= run_date)].copy()
    if df.empty:
        print(f" {ticker}: sin datos en ventana {start_date.date()} - {run_date.date()}")
        return None

    df = df.sort_index()

    # Indicadores tecnicos
    df["SMA_20"] = df["close"].rolling(window=20).mean()
    df["EMA_20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["daily_return"] = df["close"].pct_change()
    df["volatility"] = df["daily_return"].rolling(window=20).std()
    df["volume_avg"] = df["volume"].rolling(window=20).mean()

    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=14).mean()
    avg_loss = loss.rolling(window=14).mean()
    rs = avg_gain / avg_loss
    df["RSI"] = 100 - (100 / (1 + rs))

    ema_12 = df["close"].ewm(span=12, adjust=False).mean()
    ema_26 = df["close"].ewm(span=26, adjust=False).mean()
    df["MACD"] = ema_12 - ema_26
    df["MACD_signal"] = df["MACD"].ewm(span=9, adjust=False).mean()

    rolling_mean = df["close"].rolling(window=20).mean()
    rolling_std = df["close"].rolling(window=20).std()
    df["bollinger_upper"] = rolling_mean + 2 * rolling_std
    df["bollinger_lower"] = rolling_mean - 2 * rolling_std
    df["bollinger_width"] = df["bollinger_upper"] - df["bollinger_lower"]

    df = df.dropna(subset=INDICATOR_COLS).copy()
    df["ticker"] = ticker

    out_dir = ensure_date_dir(INDICADORES_BASE, date, hour)
    out_path = out_dir / f"{ticker}.parquet"
    df.to_parquet(out_path)

    print(f" Indicadores guardados para {ticker} en {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, help="Fecha en formato YYYY-MM-DD")
    parser.add_argument("--hour", type=str, help="Hora en formato HHMM")
    parser.add_argument("--lookback-days", type=int, default=400)
    args = parser.parse_args()

    date = get_execution_date(args.date)
    hour = get_execution_hour(args.hour)

    if not NORMALIZED_BASE.exists():
        print(f" No existe carpeta de precios normalizados: {NORMALIZED_BASE}")
        raise SystemExit(0)

    files = sorted(NORMALIZED_BASE.glob("*.parquet"))
    if not files:
        print(f" No hay .parquet en {NORMALIZED_BASE}")
        raise SystemExit(0)

    tickers = [p.stem for p in files]
    for ticker in tickers:
        calculate_indicators(ticker, date, hour, args.lookback_days)
