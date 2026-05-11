import argparse
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import pandas as pd

from src.utils.execution_context import (
    ensure_date_dir,
    get_execution_date,
    get_execution_hour,
)

ROOT = Path(__file__).resolve().parents[3]
RAW_BASE = ROOT / "data" / "raw" / "prices"
NORMALIZED_BASE = RAW_BASE / "normalized"
LOG_BASE = ROOT / "data" / "processed" / "prices_normalization"
PROVIDER_PRIORITY = ("yfinance", "stooq", "alphaV")

REQUIRED_COLS = ["open", "high", "low", "close", "volume"]


def _read_parquets(base_dir: Path) -> pd.DataFrame:
    files = sorted(base_dir.glob("*.parquet"))
    if not files:
        return pd.DataFrame()
    dfs = []
    for path in files:
        try:
            dfs.append(pd.read_parquet(path))
        except Exception as exc:
            print(f"[WARN] No se pudo leer {path}: {exc}")
    if not dfs:
        return pd.DataFrame()
    return pd.concat(dfs, ignore_index=True)


def _normalize_dates(series: pd.Series) -> pd.Series:
    dates = pd.to_datetime(series, errors="coerce")

    # If tz-aware -> make naive safely
    if getattr(dates.dt, "tz", None) is not None:
        dates = dates.dt.tz_convert(None)

    return dates.dt.normalize()


def _finalize_prices(df: pd.DataFrame, ticker: str, source: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    df = df.copy()
    df.columns = [str(c).lower() for c in df.columns]

    # Ensure we have a 'date' column
    if "date" not in df.columns:
        # common alternative names
        for alt in ("datetime", "timestamp"):
            if alt in df.columns:
                df = df.rename(columns={alt: "date"})
                break

    if "date" not in df.columns:
        # AlphaV often has DatetimeIndex
        if isinstance(df.index, pd.DatetimeIndex):
            df = df.reset_index().rename(columns={"index": "date"})
        else:
            print(f"[WARN] {ticker} {source}: no se encontro columna 'date' ni index datetime, se omite.")
            return pd.DataFrame()

    df["date"] = _normalize_dates(df["date"])
    df["ticker"] = ticker
    df["source"] = source

    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        print(f"[WARN] {ticker} {source}: faltan columnas {missing}, se omite.")
        return pd.DataFrame()

    for col in REQUIRED_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["date", "close"])
    df = df.drop_duplicates(subset=["date"]).sort_values("date")

    cols = ["ticker", "date"] + REQUIRED_COLS + ["source"]
    return df[cols]



def _provider_run_dir(provider: str, ticker: str, date: datetime, hour: str) -> Path | None:
    base_dir = RAW_BASE / provider / ticker / f"{date.year:04d}" / f"{date.month:02d}" / f"{date.day:02d}" / hour
    if base_dir.exists():
        return base_dir
    legacy_dir = RAW_BASE / ticker / f"{date.year:04d}" / f"{date.month:02d}" / f"{date.day:02d}" / hour
    if legacy_dir.exists():
        return legacy_dir
    return None


def _load_provider(provider: str, ticker: str, date: datetime, hour: str) -> pd.DataFrame:
    base_dir = _provider_run_dir(provider, ticker, date, hour)
    if base_dir is None:
        return pd.DataFrame()
    df = _read_parquets(base_dir)
    return _finalize_prices(df, ticker, provider)


def _merge_provider_data(provider_frames: list[tuple[str, pd.DataFrame]]) -> pd.DataFrame:
    merged = pd.DataFrame()
    for _, provider_df in provider_frames:
        if provider_df.empty:
            continue
        if merged.empty:
            merged = provider_df.copy()
            continue
        max_date = merged["date"].max()
        tail = provider_df[provider_df["date"] > max_date]
        if not tail.empty:
            merged = pd.concat([merged, tail], ignore_index=True)
    return merged


def _provider_frames_for_ticker(ticker: str, date: datetime, hour: str) -> list[tuple[str, pd.DataFrame]]:
    frames: list[tuple[str, pd.DataFrame]] = []
    for provider in PROVIDER_PRIORITY:
        provider_df = _load_provider(provider, ticker, date, hour)
        if not provider_df.empty:
            frames.append((provider, provider_df))
    return frames


def _normalize_ticker(ticker: str, date: datetime, hour: str) -> Optional[dict]:
    provider_frames = _provider_frames_for_ticker(ticker, date, hour)

    if not provider_frames:
        return None

    merged = _merge_provider_data(provider_frames)
    used_sources = [provider for provider, _ in provider_frames]

    log_row = {
        "ticker": ticker,
        "appended_rows": 0,
        "min_date": merged["date"].min(),
        "max_date": merged["date"].max(),
        "used_sources": ",".join(used_sources),
    }
    for provider in PROVIDER_PRIORITY:
        match = next((df for name, df in provider_frames if name == provider), pd.DataFrame())
        log_row[f"{provider}_rows"] = int(len(match))
    if provider_frames:
        first_df = provider_frames[0][1]
        log_row["appended_rows"] = int(len(merged) - len(first_df))

    NORMALIZED_BASE.mkdir(parents=True, exist_ok=True)
    out_path = NORMALIZED_BASE / f"{ticker}.parquet"
    if out_path.exists():
        try:
            existing = pd.read_parquet(out_path)
            combined = pd.concat([existing, merged], ignore_index=True)
        except Exception:
            combined = merged.copy()
    else:
        combined = merged.copy()

    combined = combined.drop_duplicates(subset=["date", "ticker"], keep="last").sort_values("date")
    combined.to_parquet(out_path, index=False)
    print(f"[INFO] Normalizado: {ticker} -> {out_path}")
    return log_row


def _discover_tickers(date: datetime, hour: str) -> List[str]:
    tickers = set()
    if not RAW_BASE.exists():
        return []

    for entry in RAW_BASE.iterdir():
        if not entry.is_dir() or entry.name == "normalized":
            continue
        for ticker_dir in entry.iterdir():
            if not ticker_dir.is_dir():
                continue
            run_dir = ticker_dir / f"{date.year:04d}" / f"{date.month:02d}" / f"{date.day:02d}" / hour
            if run_dir.exists() and list(run_dir.glob("*.parquet")):
                tickers.add(ticker_dir.name)

    for entry in RAW_BASE.iterdir():
        if not entry.is_dir():
            continue
        if entry.name in set(PROVIDER_PRIORITY) | {"normalized"}:
            continue
        run_dir = entry / f"{date.year:04d}" / f"{date.month:02d}" / f"{date.day:02d}" / hour
        if run_dir.exists() and list(run_dir.glob("*.parquet")):
            tickers.add(entry.name)
    return sorted(tickers)


def normalize_prices(date: datetime, hour: str) -> Path:
    tickers = _discover_tickers(date, hour)
    if not tickers:
        print("[WARN] No se encontraron tickers para normalizar.")
    log_rows = []
    for ticker in tickers:
        log_row = _normalize_ticker(ticker, date, hour)
        if log_row:
            log_rows.append(log_row)

    log_dir = ensure_date_dir(LOG_BASE, date, hour)
    log_path = log_dir / "normalization_log.parquet"
    if log_rows:
        df_log = pd.DataFrame(log_rows)
        df_log["run_date"] = date.strftime("%Y-%m-%d")
        df_log["run_hour"] = str(hour)
        df_log.to_parquet(log_path, index=False)
        print(f"[INFO] Log normalizacion: {log_path}")
    else:
        print("[WARN] No se genero log de normalizacion (sin datos).")
    return log_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, help="Fecha en formato YYYY-MM-DD")
    parser.add_argument("--hour", type=str, help="Hora en formato HHMM")
    args = parser.parse_args()

    exec_date = get_execution_date(args.date)
    exec_hour = get_execution_hour(args.hour)
    normalize_prices(exec_date, exec_hour)
