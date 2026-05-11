import pandas as pd
import numpy as np
from pathlib import Path
import argparse
import matplotlib.pyplot as plt

SIGNALS_PATH = Path("data/results/strategy_signals.csv")

def parse_args():
    parser = argparse.ArgumentParser(description="Valida señales generadas por el modelo.")
    parser.add_argument("--file", type=str, default=str(SIGNALS_PATH), help="Ruta al archivo de señales")
    return parser.parse_args()

def load_signals(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"No se encontró el archivo de señales: {path}")
    df = pd.read_csv(path)
    print(f"[INFO] Se cargaron {len(df)} señales desde: {path}")
    return df

def validate_distribution(df: pd.DataFrame):
    print("\nDistribución de señales:")
    counts = df["signal"].value_counts()
    for signal, count in counts.items():
        print(f"- {signal}: {count} ({count / len(df) * 100:.2f}%)")

def validate_scores(df: pd.DataFrame):
    print("\n Score y retorno estimado:")
    print(f"- Score promedio: {df['score'].mean():.4f}")
    print(f"- Retorno estimado promedio (%): {df['expected_return_pct'].mean():.2f}")
    print(f"- Score mínimo: {df['score'].min():.4f}")
    print(f"- Score máximo: {df['score'].max():.4f}")

def validate_by_ticker(df: pd.DataFrame):
    print("\n Cobertura por ticker:")
    tickers = df["ticker"].value_counts()
    for ticker, count in tickers.items():
        print(f"- {ticker}: {count} señales")

def plot_score_distribution(df: pd.DataFrame):
    plt.figure(figsize=(8, 5))
    plt.hist(df["score"], bins=30, color="skyblue", edgecolor="black")
    plt.title("Distribución de score de señales")
    plt.xlabel("Score")
    plt.ylabel("Frecuencia")
    plt.tight_layout()
    plt.savefig("data/results/score_distribution.png")
    plt.close()
    print("📊 Histograma de score guardado en: data/results/score_distribution.png")

def main():
    args = parse_args()
    df = load_signals(Path(args.file))
    validate_distribution(df)
    validate_scores(df)
    validate_by_ticker(df)
    plot_score_distribution(df)

if __name__ == "__main__":
    main()
