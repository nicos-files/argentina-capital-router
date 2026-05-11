import argparse
import sys
import hashlib
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from src.backtest.oos_evaluation import split_oos_by_date, train_intraday_oos_model
from src.backtest.prepare_data import prepare_data
from src.backtest.run_backtest import run_backtest


ROOT = Path(__file__).resolve().parents[2]
FEATURES_BASE = ROOT / "data" / "processed" / "features"
MODEL_PATH = ROOT / "models" / "xgb_clf_futuro.pkl"
SIM_DIR = ROOT / "simulations"
BACKTEST_CONFIG_PATH = ROOT / "src" / "backtest" / "config_backtest.json"


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d")


def _date_range(start: datetime, end: datetime):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def _is_canonical_features_path(path: Path) -> bool:
    try:
        rel_parts = path.relative_to(FEATURES_BASE).parts
    except ValueError:
        return False
    return (
        len(rel_parts) == 4
        and rel_parts[3] == "features.parquet"
        and len(rel_parts[0]) == 4
        and rel_parts[0].isdigit()
        and len(rel_parts[1]) == 2
        and rel_parts[1].isdigit()
        and len(rel_parts[2]) == 2
        and rel_parts[2].isdigit()
    )


def _available_canonical_paths() -> list[tuple[datetime, Path]]:
    rows: list[tuple[datetime, Path]] = []
    for path in FEATURES_BASE.rglob("features.parquet"):
        if not _is_canonical_features_path(path):
            continue
        parts = path.relative_to(FEATURES_BASE).parts
        rows.append((datetime.strptime(f"{parts[0]}-{parts[1]}-{parts[2]}", "%Y-%m-%d"), path))
    return sorted(rows, key=lambda item: item[0])


def _load_features_paths(paths: list[Path]) -> pd.DataFrame:
    if not paths:
        raise FileNotFoundError("No se encontraron features diarios canonicos en el rango solicitado.")

    paths = sorted(paths)
    print(f"[SIM] Selected features files: {len(paths)}")
    print(f"[SIM] First: {paths[0]}")
    print(f"[SIM] Last: {paths[-1]}")

    dfs = []
    for path in paths:
        dfs.append(pd.read_parquet(path))
    df = pd.concat(dfs, ignore_index=True)

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    elif "timestamp_proceso" in df.columns:
        df["date"] = pd.to_datetime(df["timestamp_proceso"], errors="coerce").dt.normalize()
    else:
        raise ValueError("No se encontro columna 'date' ni 'timestamp_proceso' en features.")

    df["ticker"] = df["ticker"].astype(str).str.strip()
    df = df.dropna(subset=["date", "ticker"])
    df = df.sort_values(["date", "ticker"]).drop_duplicates(subset=["date", "ticker"], keep="last")
    return df


def _write_ticker_summary(trades_rows: list[dict]) -> None:
    df = pd.DataFrame(trades_rows) if trades_rows else pd.DataFrame()
    if df.empty or "ticker" not in df.columns:
        return
    rows = []
    for ticker, group in df.groupby("ticker"):
        returns = pd.to_numeric(group.get("ret_adj"), errors="coerce")
        proba = pd.to_numeric(group.get("proba"), errors="coerce") if "proba" in group.columns else pd.Series(dtype=float)
        rows.append(
            {
                "ticker": str(ticker),
                "rows": int(len(group)),
                "mean_ret_adj": float(returns.mean()) if not returns.empty else 0.0,
                "median_ret_adj": float(returns.median()) if not returns.empty else 0.0,
                "hit_rate": float((returns > 0).mean()) if not returns.empty else 0.0,
                "mean_proba": float(proba.mean()) if not proba.empty else None,
            }
        )
    summary = sorted(rows, key=lambda item: (-float(item["mean_ret_adj"]), -float(item["hit_rate"]), item["ticker"]))
    (SIM_DIR / "simulate_ticker_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulacion de estrategia basada en features diarios.")
    parser.add_argument("--date", type=str, help="Fecha fin YYYY-MM-DD")
    parser.add_argument("--lookback-days", type=int, default=252)
    parser.add_argument("--eval-mode", choices=["oos_holdout", "in_sample"], default="oos_holdout")
    args = parser.parse_args()
    lookback_explicit = "--lookback-days" in sys.argv

    available = _available_canonical_paths()
    if not available:
        raise FileNotFoundError(f"No se encontraron features canonicos en {FEATURES_BASE}")

    if args.date:
        end_date_requested = _parse_date(args.date)
    else:
        end_date_requested = max(d for d, _ in available)

    eligible_requested = [(d, p) for d, p in available if d <= end_date_requested]
    if not eligible_requested:
        min_avail = min(d for d, _ in available).strftime("%Y-%m-%d")
        max_avail = max(d for d, _ in available).strftime("%Y-%m-%d")
        raise ValueError(
            f"No hay dias canonicos <= {end_date_requested.strftime('%Y-%m-%d')}. "
            f"Rango disponible: {min_avail}..{max_avail}."
        )

    last_available = max(d for d, _ in eligible_requested)
    if last_available != end_date_requested:
        print(
            f"[WARN] end_date_requested {end_date_requested.strftime('%Y-%m-%d')} "
            f"no disponible; usando {last_available.strftime('%Y-%m-%d')}"
        )
    end_date_effective = last_available

    eligible = [(d, p) for d, p in available if d <= end_date_effective]
    lookback_requested = args.lookback_days
    if lookback_explicit:
        if len(eligible) < lookback_requested:
            raise ValueError(
                f"Insuficientes dias canonicos: hay {len(eligible)}, se requieren {lookback_requested}."
            )
        lookback_effective = lookback_requested
    else:
        lookback_effective = min(lookback_requested, len(eligible))
        if lookback_effective != lookback_requested:
            print(
                f"[INFO] lookback_days ajustado de {lookback_requested} a {lookback_effective} "
                f"por disponibilidad de datos"
            )

    selected = eligible[-lookback_effective:]
    selected_dates = [d for d, _ in selected]
    selected_paths = [p for _, p in selected]

    df = _load_features_paths(selected_paths)
    with BACKTEST_CONFIG_PATH.open(encoding="utf-8") as f:
        cfg = json.load(f)
    oos_meta = {
        "evaluation_mode": args.eval_mode,
        "train_start_date": None,
        "train_end_date": None,
        "purge_start_date": None,
        "purge_end_date": None,
        "test_start_date": selected_dates[0].strftime("%Y-%m-%d"),
        "test_end_date": selected_dates[-1].strftime("%Y-%m-%d"),
    }
    model_ref = MODEL_PATH
    selected_feature_count = None

    if args.eval_mode == "oos_holdout":
        train_df, eval_df, oos_meta = split_oos_by_date(df)
        model_ref, selected_features = train_intraday_oos_model(train_df)
        selected_feature_count = len(selected_features)
        df = eval_df
        print("[SIM] evaluation_mode=oos_holdout")
        print(
            f"[SIM] train={oos_meta['train_start_date']}..{oos_meta['train_end_date']} "
            f"purge={oos_meta['purge_start_date']}..{oos_meta['purge_end_date']} "
            f"test={oos_meta['test_start_date']}..{oos_meta['test_end_date']}"
        )
        print(f"[SIM] rows train={len(train_df)} test={len(eval_df)} selected_features={selected_feature_count}")
    else:
        print("[SIM] evaluation_mode=in_sample")

    prepared = prepare_data(
        features_path=df,
        model_path=model_ref,
        clip_ret=cfg["CLIP_RET"],
        stop_loss=cfg["STOP_LOSS"],
        take_profit=cfg["TAKE_PROFIT"],
    )
    capital_log, daily_ret, trades_rows, day_dates = run_backtest(prepared, cfg)
    equity_summary = pd.DataFrame(capital_log) if capital_log else pd.DataFrame(
        [{"date": selected_dates[0], "capital": float(cfg["INITIAL_CAPITAL"])}]
    )
    equity_summary["date"] = pd.to_datetime(equity_summary["date"], errors="coerce")
    equity_summary["capital"] = pd.to_numeric(equity_summary["capital"], errors="coerce")
    equity_summary = equity_summary.dropna(subset=["date", "capital"]).sort_values("date")
    drawdown = (
        (equity_summary["capital"].cummax() - equity_summary["capital"]) / equity_summary["capital"].cummax()
        if not equity_summary.empty
        else pd.Series(dtype=float)
    )
    metrics = {
        "ret_total": ((float(equity_summary["capital"].iloc[-1]) / float(cfg["INITIAL_CAPITAL"])) - 1.0)
        if not equity_summary.empty
        else 0.0,
        "ret_daily_mean": float(pd.Series(daily_ret, dtype=float).mean()) if daily_ret else 0.0,
        "max_drawdown": float(drawdown.max()) if not drawdown.empty else 0.0,
        "operations": int(len(trades_rows)),
    }

    prepared_reset = prepared.reset_index()
    prepared_reset["acierto"] = (prepared_reset["prediccion"] == prepared_reset["target_clasificacion_t+1"]).astype(int)
    retorno_total = float(metrics["ret_total"])
    retorno_promedio = float(metrics["ret_daily_mean"])
    tasa_aciertos = float(prepared_reset["acierto"].mean()) if not prepared_reset.empty else 0.0
    cantidad_operaciones = int(metrics["operations"])

    SIM_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = SIM_DIR / "resultados.csv"
    pd.DataFrame(capital_log).to_csv(
        csv_path,
        index=False,
    )

    plt.figure(figsize=(10, 5))
    plt.plot(equity_summary["capital"], label="Estrategia", color="green")
    plt.axhline(float(cfg["INITIAL_CAPITAL"]), linestyle="--", color="gray", label="Capital inicial")
    plt.title("Curva de capital acumulado")
    plt.xlabel("Dias")
    plt.ylabel("Capital")
    plt.legend()
    plt.tight_layout()
    plt.savefig(SIM_DIR / "equity_curve.png")
    plt.close()

    summary = {
        "evaluation_mode": args.eval_mode,
        "target_definition": "signal_at_close_t__enter_open_t_plus_1__exit_close_t_plus_1",
        "end_date_requested": end_date_requested.strftime("%Y-%m-%d"),
        "end_date_effective": end_date_effective.strftime("%Y-%m-%d"),
        "lookback_days": lookback_effective,
        "lookback_days_requested": lookback_requested,
        "lookback_days_effective": lookback_effective,
        "selected_files_count": len(selected_paths),
        "selected_dates": [d.strftime("%Y-%m-%d") for d in selected_dates],
        "first_file": str(selected_paths[0]),
        "last_file": str(selected_paths[-1]),
        "df_shape": [int(prepared_reset.shape[0]), int(prepared_reset.shape[1])],
        "retorno_total": float(retorno_total),
        "retorno_promedio": float(retorno_promedio),
        "tasa_aciertos": float(tasa_aciertos),
        "cantidad_operaciones": int(cantidad_operaciones),
        "run_timestamp": datetime.now().isoformat(),
        "resultados_csv_sha256": None,
    }
    summary.update(oos_meta)
    if selected_feature_count is not None:
        summary["selected_features_count"] = int(selected_feature_count)
    summary["evaluated_rows"] = int(len(prepared_reset))

    if csv_path.exists():
        summary["resultados_csv_sha256"] = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    else:
        temp = dict(summary)
        temp["resultados_csv_sha256"] = None
        summary["resultados_csv_sha256"] = hashlib.sha256(
            json.dumps(temp, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    summary_path = SIM_DIR / "simulate_summary.json"
    summary_path.write_text(
        json.dumps(summary, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    _write_ticker_summary(trades_rows)

    print("\nResultados de la estrategia:")
    print(f"- Retorno total: {retorno_total:.4f}")
    print(f"- Retorno promedio diario: {retorno_promedio:.4f}")
    print(f"- Tasa de aciertos: {tasa_aciertos:.2%}")
    print(f"- Cantidad de operaciones: {cantidad_operaciones}")
    print("Resultados guardados en simulations/")


if __name__ == "__main__":
    main()
