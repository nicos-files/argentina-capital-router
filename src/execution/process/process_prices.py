import os
import pandas as pd
import argparse
from pathlib import Path
from src.utils.execution_context import (
    get_execution_date,
    get_execution_hour,
    ensure_date_dir
)
from datetime import datetime
# Unificar con el resto del pipeline
ROOT = Path(__file__).resolve().parents[3]
RAW_BASE = ROOT /"data" / "raw" / "prices"
PROCESSED_BASE = ROOT / "data" / "processed" / "prices"


REQUIRED_COLS = ["open", "high", "low", "close", "volume"]

def set_time_index(df: pd.DataFrame) -> pd.DataFrame:
    """
    Intenta setear un índice temporal estándar.
    Prioridad: 'datetime' > 'timestamp' > 'date'.
    """
    time_cols = ["datetime", "timestamp", "date"]
    for col in time_cols:
        if col in df.columns:
            # Parsear a datetime si hace falta
            if not pd.api.types.is_datetime64_any_dtype(df[col]):
                df[col] = pd.to_datetime(df[col], errors="coerce", utc=True)
            df = df.set_index(col, drop=True)
            break
    return df

def _build_raw_dir(provider: str, ticker: str, date, hour: str) -> Path:
    base = RAW_BASE / provider / ticker if provider else RAW_BASE / ticker
    return base / f"{date.year:04d}" / f"{date.month:02d}" / f"{date.day:02d}" / hour

def clean_price_data(provider: str, ticker: str, date, hour: str):
    ticker = str(ticker).split("/")[0].strip()
    if isinstance(date, str):
        date = datetime.strptime(date, "%Y-%m-%d").date()
    raw_dir = _build_raw_dir(provider, ticker, date, hour)
    if provider is None and raw_dir.exists():
        print(f" [WARN] Layout legacy usado para {ticker}: {raw_dir}")
    if not raw_dir.exists():
        legacy_dir = _build_raw_dir(None, ticker, date, hour)
        if legacy_dir.exists():
            print(f" [WARN] Layout legacy usado para {ticker}: {legacy_dir}")
            raw_dir = legacy_dir
        else:
            print(f" No se encontro carpeta de precios para {provider}/{ticker} en {raw_dir}")
            return

    archivos = list(raw_dir.glob("*.parquet"))
    if not archivos:
        print(f" No se encontró archivo parquet para {ticker} en {raw_dir}")
        return

    for archivo in archivos:
        try:
            df = pd.read_parquet(archivo)

            # Setear índice temporal si no existe
            if df.index.name is None or not pd.api.types.is_datetime64_any_dtype(df.index):
                df = set_time_index(df)

            # Orden + limpieza básica
            df = df.sort_index()
            df = df.dropna(how="any")

            # Validar columnas requeridas
            missing = [c for c in REQUIRED_COLS if c not in df.columns]
            if missing:
                print(f" {ticker}: faltan columnas {missing} en {archivo.name}, se omite.")
                continue

            # Asegurar tipos numéricos
            for c in REQUIRED_COLS:
                df[c] = pd.to_numeric(df[c], errors="coerce")
            df = df.dropna(subset=REQUIRED_COLS)

            # Guardar procesado en misma estructura temporal
            out_dir = ensure_date_dir(PROCESSED_BASE, date, hour)

            out_path = out_dir / f"{ticker}.parquet"
            #  out_path = out_dir / f"{provider}_{ticker}.parquet"  CAMBIO A FUTURO REVISAR
            df[REQUIRED_COLS].to_parquet(out_path)
            print(f" Precios procesados para {ticker}: {out_path}")

        except Exception as e:
            print(f" Error procesando {archivo}: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, help="Fecha en formato YYYY-MM-DD")
    parser.add_argument("--hour", type=str, help="Hora en formato HHMM")
    args = parser.parse_args()

    date_dt = get_execution_date(args.date)
    date = datetime.strptime(args.date, "%Y-%m-%d") if isinstance(args.date, str) else date_dt




    hour = get_execution_hour(args.hour)

    if not RAW_BASE.exists():
        print(f" No existe la base raw {RAW_BASE}")
        raise SystemExit(0)

    def _is_year_dir(path: Path) -> bool:
        return path.is_dir() and path.name.isdigit() and len(path.name) == 4

    providers = []
    legacy_tickers = []
    for entry in RAW_BASE.iterdir():
        if not entry.is_dir():
            continue
        if entry.name == "normalized":
            continue
        child_dirs = [d for d in entry.iterdir() if d.is_dir()]
        if any(_is_year_dir(d) for d in child_dirs):
            legacy_tickers.append(entry.name)
        else:
            providers.append(entry)

    for prov_dir in providers:
        provider = prov_dir.name
    
        tickers = [d.name for d in prov_dir.iterdir() if d.is_dir()]
        for ticker in tickers:
            clean_price_data(provider, ticker, date, hour)

    for ticker in legacy_tickers:
        clean_price_data(None, ticker, date, hour)
