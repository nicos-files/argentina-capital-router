# src/execution/aggregate/daily_consolidator.py

import pandas as pd
from pathlib import Path
from datetime import datetime
import argparse
from src.utils.execution_context import get_execution_date

ROOT = Path(__file__).resolve().parents[3]
MODULOS = ["prices", "fundamentals", "sentiment", "indicadores", "features"]
LOG_PATH = ROOT / "data" / "processed_daily" / "consolidation_log.parquet"

def now_iso():
    return datetime.utcnow().isoformat()

def clean_numeric_columns(df: pd.DataFrame, modulo: str) -> pd.DataFrame:
    columnas_numericas = [
        "dividend_yield", "pe_ratio", "market_cap", "volume", "price",
        "score_corto", "score_largo", "score_combinado"
    ]
    for col in columnas_numericas:
        if col in df.columns:
            try:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            except Exception as e:
                print(f"[WARNING] No se pudo convertir columna '{col}' en módulo '{modulo}': {e}")
    return df

def consolidate_module(modulo: str, date: datetime, hour: str) -> dict:
    base_dir = ROOT / "data" / "processed" / modulo / f"{date.year:04d}" / f"{date.month:02d}" / f"{date.day:02d}"
    out_path = ROOT / "data" / "processed_daily" / f"{modulo}_daily.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    errores_detectados = 0
    ticker_map = {}
    descartados = []

    if not base_dir.exists():
        return {
            "timestamp": now_iso(),
            "date": date.strftime("%Y-%m-%d"),
            "hour": hour,
            "module": modulo,
            "tickers": 0,
            "records": 0,
            "errors": 1,
            "error_msg": f"No existe {base_dir}"
        }

    archivos = list(base_dir.glob("**/*.parquet"))
    if not archivos:
        return {
            "timestamp": now_iso(),
            "date": date.strftime("%Y-%m-%d"),
            "hour": hour,
            "module": modulo,
            "tickers": 0,
            "records": 0,
            "errors": 1,
            "error_msg": f"No hay archivos en {base_dir}"
        }

    for archivo in archivos:
        ticker = archivo.stem
        if ticker == "sentimiento_general":
            ticker = "GENERAL"

        try:
            df = pd.read_parquet(archivo)
            if not df.empty and not df.isna().all(axis=1).all():
                ticker_map.setdefault(ticker, []).append(df)
                
            else:
                descartados.append({
                "archivo": archivo.name,
                "ticker": ticker,
                "razon": "vacío o solo NaN"
            })
                print(f"[WARNING] Archivo vacío o sin datos útiles: {archivo.name}")
        except Exception as e:
            errores_detectados += 1
            descartados.append({
                "archivo": archivo.name,
                "ticker": ticker,
                "razon": f"error de lectura: {e}"
            })
            print(f"[ERROR] Falló lectura de {archivo.name}: {e}")

    dfs_finales = []
    for ticker, dfs in ticker_map.items():
        try:
            
            empty_count = 0
            all_na_count = 0
            dfs_utiles = []

            for df in dfs:
                if df is None or df.empty:
                    empty_count += 1
                    continue
                
                # "all-NA" frame: after dropping rows that are entirely NA, nothing remains
                if df.dropna(how="all").empty:
                    all_na_count += 1
                    continue
                
                dfs_utiles.append(df)

            if empty_count or all_na_count:
                print(
                    f"[WARN] daily_consolidator {modulo}/{ticker}: descartados "
                    f"empty={empty_count}, all_na={all_na_count}, valid={len(dfs_utiles)}"
                )

            if not dfs_utiles:
                continue
            
            dfs_utiles = [df.dropna(axis=1, how="all") for df in dfs_utiles]
            df_final = pd.concat(dfs_utiles, ignore_index=True).drop_duplicates()
            df_final["ticker"] = ticker
            df_final = clean_numeric_columns(df_final, modulo)
            df_final["ticker"] = df_final["ticker"].astype(str).str.strip()
            dfs_finales.append(df_final)
        except Exception as e:
            errores_detectados += 1
            print(f"[ERROR] Falló consolidación de {modulo}/{ticker}: {e}")

    if not dfs_finales:
        return {
            "timestamp": now_iso(),
            "date": date.strftime("%Y-%m-%d"),
            "hour": hour,
            "module": modulo,
            "tickers": 0,
            "records": 0,
            "errors": errores_detectados,
            "error_msg": "No se pudo consolidar ningún ticker"
        }

    try:
        def es_util(df: pd.DataFrame) -> bool:
            return not df.empty and not df.isna().all().all()
        dfs_utiles = [df for df in dfs_finales if es_util(df)]
        if not dfs_utiles:
            return {
                "timestamp": now_iso(),
                "date": date.strftime("%Y-%m-%d"),
                "hour": hour,
                "module": modulo,
                "tickers": len(ticker_map),
                "records": 0,
                "errors": errores_detectados,
                "descartes": len(descartados),
                "descartes_detalle": descartados,
                "error_msg": "Todos los DataFrames finales están vacíos o sin datos útiles"
            }
        descartados_post_concat = [df for df in dfs_finales if not es_util(df)]
        print(f"[INFO] DataFrames descartados antes del concat final: {len(descartados_post_concat)}")
        dfs_utiles = [df.dropna(axis=1, how="all") for df in dfs_utiles]
        df_consolidado = pd.concat(dfs_utiles, ignore_index=True).drop_duplicates()
    except Exception as e:
        errores_detectados += 1
        return {
            "timestamp": now_iso(),
            "date": date.strftime("%Y-%m-%d"),
            "hour": hour,
            "module": modulo,
            "tickers": len(ticker_map),
            "records": 0,
            "errors": errores_detectados,
            "descartes": len(descartados),
            "descartes_detalle": descartados,
            "error_msg": f"Error al concatenar consolidado: {e}"
        }

    if out_path.exists():
        try:
            df_existente = pd.read_parquet(out_path)
            df_consolidado = pd.concat(
                [df_existente, df_consolidado], ignore_index=True
            ).drop_duplicates()
        except Exception as e:
            print(f"[WARNING] Falló la lectura del consolidado previo: {e}")

    if modulo == "sentiment" and "fecha" in df_consolidado.columns:
        df_consolidado["fecha"] = pd.to_datetime(df_consolidado["fecha"], errors="coerce")
        df_consolidado["fecha"] = df_consolidado["fecha"].dt.normalize()
    if modulo == "fundamentals":
        for col in ["net_margin", "free_cash_flow"]:
            if col in df_consolidado.columns:
                df_consolidado[col] = pd.to_numeric(df_consolidado[col], errors="coerce")
        if "ticker" in df_consolidado.columns:
            df_consolidado["ticker"] = df_consolidado["ticker"].astype(str).str.strip()

    try:
        df_consolidado.to_parquet(out_path, index=False)
        print(f"[SUCCESS] Consolidado '{modulo}' -> {out_path} ({len(df_consolidado)} registros)")
    except Exception as e:
        errores_detectados += 1
        print(f"[ERROR] Falló el guardado del consolidado '{modulo}': {e}")
        return {
            "timestamp": now_iso(),
            "date": date.strftime("%Y-%m-%d"),
            "hour": hour,
            "module": modulo,
            "tickers": len(ticker_map),
            "records": 0,
            "errors": errores_detectados,
            "descartes": len(descartados),
            "descartes_detalle": descartados,
            "error_msg": f"Error al guardar consolidado: {e}"
        }

    return {
        "timestamp": now_iso(),
        "date": date.strftime("%Y-%m-%d"),
        "hour": hour,
        "module": modulo,
        "tickers": len(ticker_map),
        "records": len(df_consolidado),
        "errors": errores_detectados,
        "descartes": len(descartados),
        "descartes_detalle": descartados,
        "error_msg": ""
    }

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, required=True)
    parser.add_argument("--hour", type=str, required=True)
    args = parser.parse_args()

    date = get_execution_date(args.date)
    hour = args.hour
    resumen_rows = []

    for modulo in MODULOS:
        print(f"\n Consolidando módulo: {modulo}")
        result = consolidate_module(modulo, date, hour)
        resumen_rows.append(result)

    df_log = pd.DataFrame(resumen_rows)

    if LOG_PATH.exists():
        try:
            df_old = pd.read_parquet(LOG_PATH)
            df_log = pd.concat([df_old, df_log], ignore_index=True).drop_duplicates()
        except Exception as e:
            print(f"[WARNING] Falló lectura del log previo: {e}")

    try:
        df_log.to_parquet(LOG_PATH, index=False)
        print(f"[INFO] Log de consolidación actualizado -> {LOG_PATH}")
    except Exception as e:
        print(f"[ERROR] Falló guardado del log de consolidación: {e}")

if __name__ == "__main__":
    main()
