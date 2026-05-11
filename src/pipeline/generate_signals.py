import argparse
from pathlib import Path
from datetime import datetime
import pandas as pd
import numpy as np
import joblib
import matplotlib.pyplot as plt
from typing import Optional

# Opcional: rutas de metadatos
META_TICKERS_PATH = Path("data/meta/ticker_metadata.csv")  # columnas esperadas: ticker,sector,avg_volume

ROOT = Path(__file__).resolve().parent.parent.parent
FEATURES_BASE = ROOT / "data" / "processed" / "features"
MODEL_PATH = ROOT / "models" / "xgb_clf_futuro.pkl"
SIGNALS_PATH = ROOT / "data" / "results" / "strategy_signals.csv"
SIMULATIONS_DIR = ROOT / "simulations"

# Columnas a excluir del set de features (no entran a X, pero sí pueden usarse para señales)
DROP_COLS = [
    "ticker", "daily_return", "target_clasificacion", "target_regresion_t+1",
    "target_clasificacion_t+1", "sentimiento_especifico", "sentimiento_general",
    "timestamp_proceso", "timestamp_ejecucion", "sector"  # ← agregado
]


def parse_args():
    parser = argparse.ArgumentParser(description="Genera señales por ticker con score, retorno estimado, riesgo y contexto.")
    parser.add_argument("--date", type=str, help="Fecha en formato YYYY-MM-DD")
    parser.add_argument("--min-score", type=float, default=0.0, help="Score mínimo para incluir señal (default: 0.0)")
    parser.add_argument("--top-n", type=int, default=0, help="Limitar a top-N por score (0 = sin límite)")
    parser.add_argument("--simulate-equity", action="store_true", help="Simular equity agregada (opcional)")
    parser.add_argument("--equity-initial", type=float, default=200.0, help="Capital inicial si se simula equity (default: 200.0)")
    return parser.parse_args()

def get_latest_features_path(base: Path):
    all_dates = sorted(base.glob("*/*/*"), reverse=True)
    for d in all_dates:
        candidate = d / "features.parquet"
        if candidate.exists():
            as_date = datetime.strptime(f"{d.parts[-3]}-{d.parts[-2]}-{d.parts[-1]}", "%Y-%m-%d")
            return candidate, as_date
    raise FileNotFoundError("No se encontró ningún archivo de features consolidado.")

def load_data(date_str: Optional[str]):
    if date_str:
        date = datetime.strptime(date_str, "%Y-%m-%d")
        path = FEATURES_BASE / f"{date.year:04d}" / f"{date.month:02d}" / f"{date.day:02d}" / "features.parquet"
        print(f"[INFO] Usando features de fecha manual: {date_str}")
    else:
        path, date = get_latest_features_path(FEATURES_BASE)
        print(f"[INFO] Usando última fecha disponible: {date.strftime('%Y-%m-%d')}")

    if not path.exists():
        raise FileNotFoundError(f"No se encontró el archivo de features: {path}")

    df = pd.read_parquet(path)

    # Filtrado mínimo para señales de largo plazo
    # Evita filtrar por labels futuros en inferencia

    return df

def load_model():
    return joblib.load(MODEL_PATH)

def enrich_with_metadata(df: pd.DataFrame) -> pd.DataFrame:
    """
    Enlaza metadata opcional (sector, avg_volume como liquidez).
    Si no existe el archivo, retorna df sin cambios.
    """
    if META_TICKERS_PATH.exists():
        meta = pd.read_csv(META_TICKERS_PATH)
        # Normalizamos nombres esperados
        cols = {c.lower(): c for c in meta.columns}
        ticker_col = cols.get("ticker", "ticker")
        sector_col = cols.get("sector", "sector")
        volume_col = cols.get("avg_volume", "avg_volume")

        meta = meta.rename(columns={
            ticker_col: "ticker",
            sector_col: "sector",
            volume_col: "avg_volume"
        })
        df = df.merge(meta[["ticker", "sector", "avg_volume"]].drop_duplicates("ticker"), on="ticker", how="left")
    else:
        df["sector"] = None
        df["avg_volume"] = np.nan
    return df

def estimate_volatility_pct(df: pd.DataFrame) -> pd.Series:
    """
    Estima volatilidad diaria en % por ticker usando la dispersión reciente.
    Prioridad:
    1) daily_return_t-1 si existe (std * 100)
    2) bollinger_width si existe (es proxy del ancho relativo; escalamos a %)
    Fallback: NaN
    """
    if "daily_return_t-1" in df.columns:
        vol = df.groupby("ticker")["daily_return_t-1"].transform(lambda s: np.nanstd(s.values) * 100.0)
        return vol
    if "bollinger_width" in df.columns:
        # bollinger_width suele ser (upper - lower) relativo; lo escalamos a porcentaje aproximado
        vol = df.groupby("ticker")["bollinger_width"].transform(lambda s: np.nanmedian(s.values) * 100.0)
        return vol
    return pd.Series(np.nan, index=df.index)

def estimate_expected_return_pct(df: pd.DataFrame, window: int = 60) -> pd.Series:
    """
    Estima retorno esperado por ticker usando mediana de retornos recientes.
    No usa labels futuros.
    """
    use_col = "daily_return_t-1" if "daily_return_t-1" in df.columns else "daily_return"
    if use_col not in df.columns:
        return pd.Series(np.nan, index=df.index)
    df_sorted = df.sort_values("timestamp_proceso") if "timestamp_proceso" in df.columns else df
    medians = df_sorted.groupby("ticker")[use_col].apply(lambda s: s.tail(window).median())
    return df["ticker"].map(medians) * 100.0

def select_latest_snapshot(df: pd.DataFrame) -> pd.DataFrame:
    if "timestamp_proceso" in df.columns:
        latest_ts = df["timestamp_proceso"].max()
        return df[df["timestamp_proceso"] == latest_ts].copy()
    return df.sort_index().groupby("ticker").tail(1).copy()

def infer_investment_type(row) -> str:
    # Umbral de 2% para “long_term” vs “intraday”
    exp_ret = row.get("expected_return_pct")
    if exp_ret is None or pd.isna(exp_ret):
        return "intraday"
    return "long_term" if abs(exp_ret) > 2.0 else "intraday"

def score_and_predict(df: pd.DataFrame, model):
    # Obtener las columnas que el modelo espera
    expected_features = model.get_booster().feature_names
    missing = [col for col in expected_features if col not in df.columns]
    if missing:
        raise ValueError(f"Faltan columnas en el dataset: {missing}")

    # Construir X con solo esas columnas
    X = df[expected_features].copy()

    # Asegurar tipos válidos
    for col in X.columns:
        if X[col].dtype == "object":
            X[col] = X[col].astype("category")

    df["score"] = model.predict_proba(X)[:, 1]
    df["prediccion"] = model.predict(X).astype(int)
    return df


def optional_equity(df: pd.DataFrame, initial_capital: float) -> pd.DataFrame:
    """
    Equity agregada muy conservadora:
    - Calcula retorno promedio por timestamp_proceso de las posiciones BUY.
    - Limita outliers.
    - Aplica cumprod a nivel timestamp para simular periodos, no tickers secuenciales.
    """
    if "timestamp_proceso" not in df.columns:
        return df  # sin timestamp, omitimos equity

    df_equity = df.copy()
    df_equity["estrategia_return"] = np.where(
        df_equity["prediccion"] == 1,
        (df_equity.get("expected_return_pct", 0.0) / 100.0),
        0.0
    )
    df_equity["estrategia_return"] = pd.to_numeric(df_equity["estrategia_return"], errors="coerce").fillna(0.0)
    df_equity["estrategia_return"] = df_equity["estrategia_return"].clip(-0.5, 0.5)

    grouped = (
        df_equity
        .groupby("timestamp_proceso", as_index=True)["estrategia_return"]
        .mean()
        .sort_index()
    )
    equity_curve = initial_capital * (1.0 + grouped).cumprod()
    out = df.copy()
    out = out.merge(equity_curve.rename("equity"), left_on="timestamp_proceso", right_index=True, how="left")
    return out

def generate_signals(df: pd.DataFrame) -> list[dict]:
    signals = []
    for _, row in df.iterrows():
        retorno_pct = 0.0
        if "expected_return_pct" in df.columns and not pd.isna(row["expected_return_pct"]):
            retorno_pct = round(float(row["expected_return_pct"]), 2)
        sentimiento = None
        # Si tenés ambas columnas, combinamos; si no, usamos la disponible
        if "sentimiento_especifico" in df.columns and "sentimiento_general" in df.columns:
            try:
                sentimiento = float(np.nanmean([row["sentimiento_especifico"], row["sentimiento_general"]]))
            except Exception:
                sentimiento = None
        elif "sentimiento_especifico" in df.columns:
            sentimiento = row["sentimiento_especifico"]
        elif "sentimiento_general" in df.columns:
            sentimiento = row["sentimiento_general"]

        signals.append({
            "ticker": row["ticker"],
            "score": round(float(row["score"]), 4),
            "expected_return_pct": retorno_pct,
            "signal": "BUY" if int(row["prediccion"]) == 1 else "HOLD",
            "investment_type": infer_investment_type(row),
            "timestamp_proceso": row["timestamp_proceso"],
            "volatilidad_pct": None if pd.isna(row.get("volatilidad_pct", np.nan)) else round(float(row["volatilidad_pct"]), 2),
            "sector": None if pd.isna(row.get("sector", None)) else row.get("sector", None),
            "liquidez": None if pd.isna(row.get("avg_volume", np.nan)) else int(row["avg_volume"]),
            "sentimiento": None if sentimiento is None or pd.isna(sentimiento) else round(float(sentimiento), 4),
        })
    return signals

def filter_and_rank(signals: list[dict], min_score: float, top_n: int) -> list[dict]:
    filtered = [s for s in signals if s.get("score", 0.0) >= min_score]
    # Orden principal por score desc; secundario por expected_return_pct desc
    filtered.sort(key=lambda s: (s.get("score", 0.0), s.get("expected_return_pct", 0.0)), reverse=True)
    if top_n and top_n > 0:
        filtered = filtered[:top_n]
    return filtered

def save_signals(signals: list[dict]):
    SIGNALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(signals).to_csv(SIGNALS_PATH, index=False)
    print(f" Señales guardadas en: {SIGNALS_PATH}")

def save_equity_outputs(df: pd.DataFrame):
    SIMULATIONS_DIR.mkdir(parents=True, exist_ok=True)
    # Guardamos equity por timestamp si está calculada
    if "equity" in df.columns:
        df_equity = df[["timestamp_proceso", "equity"]].drop_duplicates().sort_values("timestamp_proceso")
        df_equity.to_csv(SIMULATIONS_DIR / "equity_by_timestamp.csv", index=False)

        plt.figure(figsize=(10, 5))
        plt.plot(pd.to_datetime(df_equity["timestamp_proceso"]), df_equity["equity"], label="Estrategia (agregada por timestamp)", color="green")
        plt.title("Curva de capital agregada por timestamp")
        plt.xlabel("Tiempo")
        plt.ylabel("Capital")
        plt.legend()
        plt.tight_layout()
        plt.savefig(SIMULATIONS_DIR / "equity_curve.png")
        plt.close()
        print(f" Equity guardada en: {SIMULATIONS_DIR}")

def print_summary(signals: list[dict]):
    total = len(signals)
    buys = sum(1 for s in signals if s["signal"] == "BUY")
    avg_score = np.mean([s["score"] for s in signals]) if signals else 0.0
    avg_ret = np.mean([s["expected_return_pct"] for s in signals]) if signals else 0.0
    print("\n Resumen de señales:")
    print(f"- Total de señales: {total}")
    print(f"- Señales BUY: {buys}")
    print(f"- Score promedio: {avg_score:.4f}")
    print(f"- Retorno estimado promedio (%): {avg_ret:.2f}")

def main():
    args = parse_args()
    df_all = load_data(args.date)
    df_all = enrich_with_metadata(df_all)
    df_all["volatilidad_pct"] = estimate_volatility_pct(df_all)
    df_all["expected_return_pct"] = estimate_expected_return_pct(df_all)

    # Score y predicción
    model = load_model()
    df_latest = select_latest_snapshot(df_all)
    df_latest = score_and_predict(df_latest, model)

    signals_latest = generate_signals(df_latest)
    signals_latest = filter_and_rank(signals_latest, min_score=args.min_score, top_n=args.top_n)

    # Guardar snapshot separado
    latest_path = SIGNALS_PATH.parent / "strategy_signals_latest.csv"
    pd.DataFrame(signals_latest).to_csv(latest_path, index=False)
    print(f" Señales (snapshot) guardadas en: {latest_path}")
    
    # 2) (Opcional) Histórico para análisis/backtest por señales
    # OJO: esto puede ser pesado si tenés muchos años/tickers
    df_hist = df_all.copy()
    df_hist = score_and_predict(df_hist, model)
    
    signals_hist = generate_signals(df_hist)
    hist_path = SIGNALS_PATH.parent / "strategy_signals_history.csv"
    pd.DataFrame(signals_hist).to_csv(hist_path, index=False)
    print(f" Señales (histórico) guardadas en: {hist_path}")
    
    print_summary(signals_latest)

if __name__ == "__main__":
    main()

