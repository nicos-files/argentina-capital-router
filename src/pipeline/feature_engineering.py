import os
import pandas as pd
import sys
import time
from datetime import datetime
from pathlib import Path
import argparse

from src.utils.llm_logger import log_llm_interaction
from src.utils.execution_context import (
    ensure_date_dir,
    get_etl_args,
    get_current_args,
    get_execution_date
)


def load_parquet(path):
    return pd.read_parquet(path) if os.path.exists(path) else pd.DataFrame()


def _expected_fundamental_cols():
    try:
        from src.execution.process.process_fundamentals import alpha_cols, finnhub_cols
        return sorted(set(alpha_cols.values()) | set(finnhub_cols.values()))
    except Exception:
        return []


def consolidate_daily_features(date: datetime):
    base_dir = Path("data/processed/features") / f"{date.year:04d}" / f"{date.month:02d}" / f"{date.day:02d}"
    hourly_files = list(base_dir.glob("*/features.parquet"))

    dfs = []
    for f in hourly_files:
        try:
            df = pd.read_parquet(f)
            dfs.append(df)
        except Exception as e:
            print(f"[WARN] No se pudo leer {f}: {e}")

    if dfs:
        df_day = pd.concat(dfs, ignore_index=True).sort_index()
        output_path = base_dir / "features.parquet"
        df_day.to_parquet(output_path)
        print(f"[INFO] Consolidado diario guardado en {output_path}")
        print(f"[INFO] Total de muestras consolidadas: {len(df_day)}")
    else:
        print(f"[WARN] No se encontraron features horarios para consolidar en {base_dir}")


def combine_features(date: datetime, hour: str, mode: str):
    output_dir = ensure_date_dir(Path("data/processed/features"), date, hour)

    # 1. Cargar los daily consolidados
    df_prices = load_parquet("data/processed_daily/prices_daily.parquet")
    df_sentimiento = load_parquet("data/processed_daily/sentiment_daily.parquet")
    df_fundamentals = load_parquet("data/processed_daily/fundamentals_daily.parquet")
    df_indicadores = load_parquet("data/processed_daily/indicadores_daily.parquet")

    # 2. Debug
    def _dbg_df(name, df):
        print(f"[DEBUG] {name}: shape={df.shape}")
        print(f"[DEBUG] {name}: cols={list(df.columns)[:30]}")
        if "ticker" in df.columns:
            print(f"[DEBUG] {name}: tickers_sample={sorted(df['ticker'].astype(str).unique())[:20]}")
        idx_name = getattr(df.index, "name", None)
        print(f"[DEBUG] {name}: index_name={idx_name}, index_type={type(df.index)}")

    _dbg_df("prices_daily", df_prices)
    _dbg_df("indicadores_daily", df_indicadores)
    _dbg_df("fundamentals_daily", df_fundamentals)
    _dbg_df("sentiment_daily", df_sentimiento)

    if df_prices.empty or "ticker" not in df_prices.columns:
        raise RuntimeError("feature_engineering: prices_daily vacio o sin ticker.")
    if df_indicadores.empty or "ticker" not in df_indicadores.columns:
        raise RuntimeError("feature_engineering: indicadores_daily vacio o sin ticker.")

    tickers_common = (
    set(df_prices["ticker"].astype(str))
    & set(df_indicadores["ticker"].astype(str))
)

    if df_fundamentals.empty or "ticker" not in df_fundamentals.columns:
        print("[WARN] fundamentals_daily ausente o vacio. Se rellenara con NaN.")

    if df_sentimiento.empty or "ticker" not in df_sentimiento.columns:
        print("[WARN] sentiment_daily ausente o vacio. Se usaran ceros.")


    print(f"[DEBUG] tickers_common({len(tickers_common)}): {sorted(list(tickers_common))[:50]}")

    # 3. Sentimiento GENERAL
    sentimiento_valor = 0.0
    if not df_sentimiento.empty and "sentimiento_combinado" in df_sentimiento.columns:
        sentimiento_general = df_sentimiento[df_sentimiento["ticker"] == "GENERAL"]
        if not sentimiento_general.empty:
            sentimiento_valor = float(sentimiento_general["sentimiento_combinado"].iloc[0])
    print(f"[DEBUG] sentimiento_general={sentimiento_valor}")

    fundamental_cols = [c for c in df_fundamentals.columns if c != "ticker"] if not df_fundamentals.empty else _expected_fundamental_cols()

    all_rows = []

    for ticker in sorted(list(tickers_common)):
        start = time.time()

        try:
            df_ind = df_indicadores[df_indicadores["ticker"] == ticker].copy()
            if df_ind.empty:
                print(f"[DEBUG] SKIP {ticker}: indicadores vacios")
                continue

            fundamentos = pd.DataFrame()
            if not df_fundamentals.empty and "ticker" in df_fundamentals.columns:
                fundamentos = df_fundamentals[df_fundamentals["ticker"] == ticker]

            if fundamental_cols:
                for col in fundamental_cols:
                    if not fundamentos.empty and col in fundamentos.columns:
                        df_ind.loc[:, col] = fundamentos[col].iloc[0]
                    else:
                        df_ind.loc[:, col] = pd.NA

            sent_valor = sentimiento_valor
            if not df_sentimiento.empty and "sentimiento_combinado" in df_sentimiento.columns:
                sentimiento_especifico = df_sentimiento[df_sentimiento["ticker"] == ticker]
                if not sentimiento_especifico.empty:
                    sent_valor = float(sentimiento_especifico["sentimiento_combinado"].iloc[0])

            df_ind["sentimiento_especifico"] = sent_valor
            df_ind["sentimiento_general"] = sentimiento_valor
            df_ind["ticker"] = ticker

            all_rows.append(df_ind)

            duration = time.time() - start
            print(f"[DEBUG] OK {ticker}: cols={len(df_ind.columns)} rows={len(df_ind)} dur={duration:.2f}s")

        except Exception as e:
            print(f"[ERROR] {ticker}: {e}")
            continue

    if not all_rows:
        raise RuntimeError("feature_engineering: all_rows vacio. Revisar logs [DEBUG].")

    df_final = pd.concat(all_rows, ignore_index=False).sort_index()

    # Enriquecimiento temporal
    df_final["RSI_t-1"] = df_final.groupby("ticker")["RSI"].shift(1)
    df_final["daily_return_t-1"] = df_final.groupby("ticker")["daily_return"].shift(1)
    df_final["MACD_t-1"] = df_final.groupby("ticker")["MACD"].shift(1)

    # Fix: shares_outstanding puede venir como string con comas
    if "shares_outstanding" in df_final.columns:
        df_final["shares_outstanding"] = (
            df_final["shares_outstanding"].astype(str).str.replace(",", "", regex=False)
        )
        df_final["shares_outstanding"] = pd.to_numeric(df_final["shares_outstanding"], errors="coerce")

    # Conversion numerica (evitar convertir columnas no numericas)
    non_numeric = {"ticker", "date", "timestamp_proceso", "timestamp_ejecucion"}
    for col in df_final.columns:
        if col in non_numeric:
            continue
        df_final[col] = pd.to_numeric(df_final[col], errors="coerce")


    # Targets y combinaciones
    df_final["target_clasificacion"] = (df_final["daily_return"] > 0).astype(int)
    df_final["RSI_x_volume"] = df_final["RSI"] * df_final["volume_avg"]
    df_final["MACD_x_sentimiento"] = df_final["MACD"] * df_final["sentimiento_general"]

    # Validacion
    columns_to_check = [
        "bollinger_upper", "bollinger_lower", "bollinger_width",
        "RSI_t-1", "daily_return_t-1", "MACD_t-1"
    ]
    missing_cols = [col for col in columns_to_check if col not in df_final.columns]
    if missing_cols:
        print(f" Faltan columnas esperadas: {missing_cols}")
    else:
        nulls = df_final[columns_to_check].isnull().mean()
        print("Validacion de columnas enriquecidas (porcentaje de NaNs):")
        print(nulls.sort_values(ascending=False))

    # Keep rows; drop only where the core indicators are missing
    core_cols = ["RSI", "MACD", "MACD_signal", "bollinger_upper", "bollinger_lower", "bollinger_width", "daily_return"]
    df_final = df_final.dropna(subset=[c for c in core_cols if c in df_final.columns])

    lag_cols = ["RSI_t-1", "daily_return_t-1", "MACD_t-1"]
    df_final = df_final.dropna(subset=[c for c in lag_cols if c in df_final.columns])
    # Targets futuros
    df_final["target_regresion_t+1"] = df_final.groupby("ticker")["daily_return"].shift(-1)
    df_final["target_clasificacion_t+1"] = (df_final["target_regresion_t+1"] > 0.005).astype(int)
    if mode == "train":
        df_final = df_final.dropna(subset=["target_regresion_t+1"])

    # Timestamp del proceso (viene del orquestador)
    timestamp_proceso = datetime(
        year=date.year,
        month=date.month,
        day=date.day,
        hour=int(hour[:2]),
        minute=int(hour[2:])
    )
    timestamp_ejecucion = datetime.now()
    df_final["timestamp_proceso"] = timestamp_proceso
    df_final["timestamp_ejecucion"] = timestamp_ejecucion

    # Guardar archivo horario
    output_path = output_dir / "features.parquet"
    df_final.to_parquet(output_path)
    print(f"Features horarios guardados en {output_path}")
    print(f"Total de muestras: {len(df_final)}")
    print("Preview:")
    print(df_final.head())

    # Consolidar el dia completo
    consolidate_daily_features(date)



def parse_args():
    parser = argparse.ArgumentParser(description="Genera features diarios combinando modulos procesados.")
    parser.add_argument("--mode", choices=["train","inference"], default="train")
    parser.add_argument("--date", type=str, help="Fecha de ejecucion en formato YYYY-MM-DD")
    parser.add_argument("--hour", type=str, help="Hora de ejecucion en formato HHMM")
    parser.add_argument("--from-etl", action="store_true", help="Usar fecha/hora del ultimo ETL")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if args.date and args.hour:
        date = args.date
        hour = args.hour
        print(f"[INFO] Usando fecha/hora manual: {date} {hour}")
    elif args.from_etl:
        etl_args = get_etl_args()
        date = etl_args["date"]
        hour = etl_args["hour"]
        print(f"[INFO] Usando fecha/hora del ultimo ETL: {date} {hour}")
    else:
        current_args = get_current_args()
        date = current_args["date"]
        hour = current_args["hour"]
        print(f"[INFO] Usando fecha/hora actual: {date} {hour}")

    combine_features(get_execution_date(date), hour, args.mode)

