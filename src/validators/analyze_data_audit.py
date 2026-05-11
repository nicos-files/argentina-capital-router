import pandas as pd
import pathlib
from datetime import datetime

AUDIT_DIR = pathlib.Path("data/exports/validation_reports")
OUTPUT_DIR = pathlib.Path("data/exports/validation_reports")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def load_latest_audit():
    files = sorted(AUDIT_DIR.glob("raw_data_audit_*.csv"), reverse=True)
    if not files:
        raise FileNotFoundError("No se encontró ningún archivo de auditoría.")
    print(f"📥 Usando archivo: {files[0].name}")
    return pd.read_csv(files[0])

def analyze(df):
    df["has_error"] = df["error"].notna()
    df["valid"] = (
        (df["error"].isna()) &
        (df["n_rows"].fillna(0) > 0) &
        (df["n_nulls"].fillna(0) == 0)
    )

    summary = df.groupby(["source", "ticker"]).agg({
        "valid": "mean",
        "n_rows": "sum",
        "n_nulls": "sum",
        "n_duplicates": "sum",
        "file": "count"
    }).reset_index()

    summary["valid_pct"] = (summary["valid"] * 100).round(2)
    summary["status"] = summary["valid_pct"].apply(lambda x: "✅ OK" if x == 100 else "⚠️ Parcial" if x > 50 else "❌ Crítico")
    return summary

def save_summary(summary):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    output_path = OUTPUT_DIR / f"raw_data_quality_summary_{timestamp}.csv"
    summary.to_csv(output_path, index=False)
    print(f"✅ Resumen guardado en: {output_path}")

def run():
    df = load_latest_audit()
    summary = analyze(df)
    save_summary(summary)

if __name__ == "__main__":
    run()
