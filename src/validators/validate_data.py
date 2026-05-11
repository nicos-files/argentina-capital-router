import pandas as pd
import pathlib
from datetime import datetime

# Configuración
RAW_ROOT = pathlib.Path("data/raw")
RAW_SOURCES = ["alphaV", "prices", "sentiment", "fundamentals"]
SUMMARY_DIR = pathlib.Path("data/exports/validation_reports")
SUMMARY_DIR.mkdir(parents=True, exist_ok=True)

def extract_metadata(file_path):
    """
    Extrae source, ticker y date_path desde la ruta del archivo.
    Ejemplo: data/raw/prices/AMD.US/2025/10/02/1533/prices_AMD.US.parquet
    """
    parts = file_path.parts
    try:
        source = parts[2]  # alphaV, prices, etc.
        ticker = parts[3]
        date_path = "/".join(parts[4:8])  # yyyy/mm/dd/hhmm
    except IndexError:
        source, ticker, date_path = "unknown", "unknown", "unknown"
    return source, ticker, date_path

def audit_parquet(file_path):
    source, ticker, date_path = extract_metadata(file_path)
    try:
        df = pd.read_parquet(file_path)
        summary = {
            "source": source,
            "ticker": ticker,
            "date_path": date_path,
            "file": str(file_path),
            "n_rows": len(df),
            "n_columns": len(df.columns),
            "columns": ", ".join(df.columns),
            "n_nulls": int(df.isnull().sum().sum()),
            "n_duplicates": int(df.duplicated().sum()),
            "start_date": str(df.index.min()) if df.index.is_monotonic_increasing else None,
            "end_date": str(df.index.max()) if df.index.is_monotonic_increasing else None,
            "error": None
        }
    except Exception as e:
        summary = {
            "source": source,
            "ticker": ticker,
            "date_path": date_path,
            "file": str(file_path),
            "n_rows": None,
            "n_columns": None,
            "columns": None,
            "n_nulls": None,
            "n_duplicates": None,
            "start_date": None,
            "end_date": None,
            "error": str(e)
        }
    return summary

def run_audit():
    all_results = []
    for source in RAW_SOURCES:
        source_path = RAW_ROOT / source
        print(f"🔍 Auditando fuente: {source}")
        parquet_files = list(source_path.rglob("*.parquet"))
        for file_path in parquet_files:
            result = audit_parquet(file_path)
            all_results.append(result)
    return all_results

def save_report(results):
    df = pd.DataFrame(results)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    output_path = SUMMARY_DIR / f"raw_data_audit_{timestamp}.csv"
    df.to_csv(output_path, index=False)
    print(f"✅ Reporte guardado en: {output_path}")

def run():
    results = run_audit()
    save_report(results)

if __name__ == "__main__":
    run()
