import pandas as pd
import pathlib
import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt
from datetime import datetime

FEATURES_DIR = pathlib.Path("data/processed/features")
REPORT_DIR = pathlib.Path("data/exports/validation_reports")
REPORT_DIR.mkdir(parents=True, exist_ok=True)

def load_all_features():
    files = list(FEATURES_DIR.rglob("*.parquet"))
    dfs = []
    for f in files:
        try:
            df = pd.read_parquet(f)
            df["ticker"] = f.parts[-5]  # Asumiendo estructura: features/TICKER/yyyy/mm/dd/HHMM/file.parquet
            dfs.append(df)
        except Exception as e:
            print(f"❌ Error al leer {f}: {e}")
    return pd.concat(dfs, ignore_index=True)

def analyze_features(df):
    numeric_cols = df.select_dtypes(include=np.number).columns
    summary = pd.DataFrame(index=numeric_cols)

    summary["n_nulls"] = df[numeric_cols].isnull().sum()
    summary["pct_nulls"] = (summary["n_nulls"] / len(df) * 100).round(2)
    summary["mean"] = df[numeric_cols].mean()
    summary["std"] = df[numeric_cols].std()
    summary["min"] = df[numeric_cols].min()
    summary["max"] = df[numeric_cols].max()
    summary["zero_var"] = (summary["std"] == 0)
    summary["outliers"] = ((df[numeric_cols] > summary["mean"] + 3 * summary["std"]) | 
                           (df[numeric_cols] < summary["mean"] - 3 * summary["std"])).sum()

    return summary.reset_index().rename(columns={"index": "feature"})

def plot_correlations(df, output_path):
    numeric_cols = df.select_dtypes(include=np.number).columns
    corr = df[numeric_cols].corr()
    plt.figure(figsize=(12, 10))
    sns.heatmap(corr, cmap="coolwarm", center=0, annot=False)
    plt.title("Feature Correlation Matrix")
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()

def save_summary(summary):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    output_path = REPORT_DIR / f"features_quality_summary_{timestamp}.csv"
    summary.to_csv(output_path, index=False)
    print(f"✅ Reporte guardado en: {output_path}")

def run():
    df = load_all_features()
    print(f"📦 Features cargados: {len(df)} filas, {len(df.columns)} columnas")
    summary = analyze_features(df)
    save_summary(summary)
    plot_correlations(df, REPORT_DIR / "features_correlation_matrix.png")

if __name__ == "__main__":
    run()
