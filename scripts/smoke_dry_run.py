import os
import sys
from pathlib import Path
from datetime import datetime
import subprocess
import numpy as np
import pandas as pd


def make_synthetic_features(out_path: Path, n_days: int = 90):
    tickers = ["AAA.US", "BBB.US"]
    end_date = datetime.strptime("2000-01-01", "%Y-%m-%d")
    dates = pd.date_range(end=end_date, periods=n_days, freq="D")

    rows = []
    for ticker in tickers:
        daily_return = np.random.normal(loc=0.001, scale=0.02, size=n_days)
        for i, dt in enumerate(dates):
            rows.append({
                "ticker": ticker,
                "timestamp_proceso": dt,
                "timestamp_ejecucion": datetime.utcnow(),
                "daily_return": daily_return[i],
                "daily_return_t-1": daily_return[i - 1] if i > 0 else np.nan,
                "RSI": np.random.uniform(30, 70),
                "MACD": np.random.normal(0, 0.5),
                "volume_avg": np.random.uniform(1e5, 5e5),
                "bollinger_width": np.random.uniform(0.5, 2.0),
                "sentimiento_especifico": np.random.uniform(-1, 1),
                "sentimiento_general": np.random.uniform(-1, 1),
            })

    df = pd.DataFrame(rows)
    df["target_regresion_t+1"] = df.groupby("ticker")["daily_return"].shift(-1)
    df["target_clasificacion"] = (df["daily_return"] > 0).astype(int)
    df["target_clasificacion_t+1"] = (df["target_regresion_t+1"] > 0.005).astype(int)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)


def run_cmd(args):
    print(f"[SMOKE] Ejecutando: {' '.join(args)}")
    res = subprocess.run(args, capture_output=True, text=True)
    if res.returncode != 0:
        print(res.stdout)
        print(res.stderr)
        raise RuntimeError(f"Fallo comando: {' '.join(args)}")
    return res


def main():
    root = Path(__file__).resolve().parents[1]
    date_str = "2000-01-01"
    features_path = root / "data" / "processed" / "features" / "2000" / "01" / "01" / "features.parquet"

    np.random.seed(42)
    make_synthetic_features(features_path)

    python_exe = sys.executable
    run_cmd([python_exe, "-m", "src.pipeline.train_model", "--date", date_str])
    run_cmd([python_exe, "-m", "src.pipeline.generate_signals", "--date", date_str, "--top-n", "5"])
    run_cmd([python_exe, "-m", "src.backtest.backtest_strategy", "--date", date_str])

    signals_path = root / "data" / "results" / "strategy_signals.csv"
    model_path = root / "models" / "xgb_clf_futuro.pkl"
    equity_path = root / "simulations" / "equity_curve.csv"

    checks = {
        "features": features_path.exists(),
        "model": model_path.exists(),
        "signals": signals_path.exists(),
        "equity": equity_path.exists(),
    }
    print("[SMOKE] Checks:", checks)
    if not all(checks.values()):
        raise SystemExit("Smoke test incompleto: falta algun artefacto.")
    print("[SMOKE] OK")


if __name__ == "__main__":
    main()
