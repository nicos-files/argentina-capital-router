import pandas as pd
import numpy as np
from typing import List, Dict, Tuple


def run_backtest(df: pd.DataFrame, cfg: dict) -> Tuple[List[Dict], List[float], List[Dict], List[pd.Timestamp]]:
    """
    Backtest simple por fecha:
    - Selecciona BUY segun prediccion y umbral de probabilidad.
    - Aplica costos y calcula equity diaria.
    """
    max_positions = int(cfg.get("MAX_POSITIONS", 5))
    min_proba = float(cfg.get("MIN_PROBA", 0.5))
    commission_side = float(cfg.get("COMMISSION_SIDE", 0.0005))
    slippage_side = float(cfg.get("SLIPPAGE_SIDE", 0.0003))
    initial_capital = float(cfg.get("INITIAL_CAPITAL", 100.0))
    total_cost = 2.0 * (commission_side + slippage_side)

    df = df.reset_index()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()

    capital = initial_capital
    capital_log = []
    daily_ret = []
    trades_rows = []
    day_dates = []

    for day, g in df.groupby("date"):
        day_dates.append(day)
        g = g.copy()

        if "proba" in g.columns:
            g = g[g["proba"] >= min_proba]
            g = g.sort_values("proba", ascending=False)
        else:
            g = g[g["prediccion"] == 1]

        if g.empty:
            daily_ret.append(0.0)
            capital_log.append({"date": day, "capital": capital})
            continue

        if max_positions > 0:
            g = g.head(max_positions)

        avg_ret = float(g["ret_adj"].mean()) if "ret_adj" in g.columns else 0.0
        net_ret = avg_ret - total_cost

        capital *= (1.0 + net_ret)
        daily_ret.append(net_ret)
        capital_log.append({"date": day, "capital": capital})

        for _, row in g.iterrows():
            trades_rows.append({
                "date": day,
                "ticker": row.get("ticker"),
                "ret_adj": row.get("ret_adj"),
                "proba": row.get("proba"),
            })

    return capital_log, daily_ret, trades_rows, day_dates
