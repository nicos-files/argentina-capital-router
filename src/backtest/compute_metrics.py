import json
import numpy as np
import pandas as pd
from pathlib import Path
from typing import List, Dict, Tuple, Any


def compute_metrics(
    capital_log: List[Dict[str, Any]],
    daily_ret: List[float],
    trades_rows: List[Dict[str, Any]],
    day_dates,
    out_dir: Path,
    cfg: dict
) -> Tuple[pd.DataFrame, Dict[str, float]]:
    """
    Esperado:
      - capital_log: lista de dicts, idealmente con {"date": ..., "capital": ...}
      - daily_ret: lista de retornos diarios (float)
      - day_dates: lista/serie de fechas (mismo largo que daily_ret idealmente)
    """

    out_dir.mkdir(parents=True, exist_ok=True)
    initial_capital = float(cfg.get("INITIAL_CAPITAL", 100.0))

    # 1) Intentar equity desde capital_log
    df_equity = pd.DataFrame(capital_log) if capital_log else pd.DataFrame()

    if not df_equity.empty:
        # Normalizar columnas esperadas
        if "date" in df_equity.columns:
            df_equity["date"] = pd.to_datetime(df_equity["date"], errors="coerce").dt.date
        if "capital" in df_equity.columns:
            df_equity["capital"] = pd.to_numeric(df_equity["capital"], errors="coerce")
        df_equity = df_equity.dropna(subset=[c for c in ["date", "capital"] if c in df_equity.columns])

        # Si faltan columnas, lo consideramos inválido y reconstruimos
        if not {"date", "capital"}.issubset(df_equity.columns):
            df_equity = pd.DataFrame()

    # 2) Fallback: reconstruir equity desde daily_ret + day_dates
    if df_equity.empty:
        dates = pd.Series(pd.to_datetime(day_dates, errors="coerce")) if day_dates is not None else pd.Series([], dtype="datetime64[ns]")
        rets = pd.Series(daily_ret, dtype="float64") if daily_ret else pd.Series([], dtype="float64")

        n = int(min(len(dates), len(rets)))

        # DatetimeIndex no tiene .iloc -> usar Series antes de slice uniforme
        dates = dates.iloc[:n]
        rets = rets.iloc[:n]

        if n > 0:
            capital = initial_capital * (1.0 + rets.fillna(0.0)).cumprod()
            df_equity = pd.DataFrame({
                "date": dates.dt.date,
                "capital": capital.astype(float),
            })
        else:
            # Último fallback: curva plana de 1 punto
            df_equity = pd.DataFrame({
                "date": [pd.Timestamp.utcnow().date()],
                "capital": [float(initial_capital)],
            })

    # Orden, dedupe y guardar CSV
    df_equity = df_equity.sort_values("date").drop_duplicates(subset=["date"], keep="last")
    equity_path = out_dir / "equity_curve.csv"
    df_equity.to_csv(equity_path, index=False)

    # Métricas
    if df_equity.empty:
        metrics = {"ret_total": 0.0, "ret_daily_mean": 0.0, "max_drawdown": 0.0, "operations": 0}
        summary = df_equity
    else:
        ret_total = (float(df_equity["capital"].iloc[-1]) / initial_capital) - 1.0
        ret_daily_mean = float(np.mean(daily_ret)) if daily_ret else 0.0

        cap = df_equity["capital"].astype(float)
        dd = (cap.cummax() - cap) / cap.cummax()
        max_drawdown = float(dd.max()) if not dd.empty else 0.0

        operations = len(trades_rows)
        metrics = {
            "ret_total": float(ret_total),
            "ret_daily_mean": float(ret_daily_mean),
            "max_drawdown": float(max_drawdown),
            "operations": int(operations),
        }
        summary = df_equity

    summary_path = out_dir / "backtest_summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    return summary, metrics
