from pathlib import Path
import json
import argparse
from datetime import datetime, timedelta
from typing import Optional, List
import numpy as np
import pandas as pd
from .prepare_data import prepare_data
from .run_backtest import run_backtest
from .compute_metrics import compute_metrics
from .plot_equity import plot_equity_curve
from .oos_evaluation import split_oos_by_date, train_intraday_oos_model

# Paths
ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = ROOT / "src" / "backtest" / "config_backtest.json"
FEATURES_BASE = ROOT / "data" / "processed" / "features"
MODEL_PATH = ROOT / "models" / "xgb_clf_futuro.pkl"
OUT_DIR = ROOT / "simulations"


def get_latest_features_path(base: Path) -> Path:
    all_dates = sorted(base.glob("*/*/*"), reverse=True)
    for d in all_dates:
        candidate = d / "features.parquet"
        if candidate.exists():
            return candidate
    raise FileNotFoundError("No se encontro ningun archivo de features consolidado.")


def _date_from_features_path(path: Path) -> datetime:
    parts = path.parts
    if len(parts) < 4:
        raise ValueError(f"Ruta invalida para fecha: {path}")
    year = parts[-4]
    month = parts[-3]
    day = parts[-2]
    return datetime.strptime(f"{year}-{month}-{day}", "%Y-%m-%d")


def _date_range(start: datetime, end: datetime) -> List[datetime]:
    days = []
    cur = start
    while cur <= end:
        days.append(cur)
        cur += timedelta(days=1)
    return days


def load_features_range(start_date: datetime, end_date: datetime) -> pd.DataFrame:
    paths = []
    for day in _date_range(start_date, end_date):
        day_dir = FEATURES_BASE / f"{day.year:04d}" / f"{day.month:02d}" / f"{day.day:02d}"
        daily_file = day_dir / "features.parquet"
        if daily_file.exists():
            paths.append(daily_file)
        else:
            run_files = sorted(day_dir.glob("*/features.parquet"))
            if run_files:
                print(f"[WARN] Se ignoran features por run_id en {day_dir}: {len(run_files)} archivos")
            print(f"[WARN] No se encontro features diario: {daily_file}")

    if not paths:
        raise FileNotFoundError("No se encontraron features diarios en el rango solicitado.")

    print("[BACKTEST] Features paths:")
    for path in paths:
        print(f"  - {path}")

    unexpected = []
    for path in paths:
        try:
            rel_parts = path.relative_to(FEATURES_BASE).parts
        except ValueError:
            rel_parts = ()
        ok = (
            len(rel_parts) == 4
            and rel_parts[3] == "features.parquet"
            and len(rel_parts[0]) == 4
            and rel_parts[0].isdigit()
            and len(rel_parts[1]) == 2
            and rel_parts[1].isdigit()
            and len(rel_parts[2]) == 2
            and rel_parts[2].isdigit()
        )
        if not ok:
            unexpected.append(path)
    if unexpected:
        raise ValueError(f"Se encontraron paths no canonicos: {unexpected}")

    offenders = []
    for path in paths:
        try:
            df_head = pd.read_parquet(path)
            if "source" in df_head.columns:
                offenders.append(str(path))
        except Exception as exc:
            print(f"[WARN] No se pudo inspeccionar {path}: {exc}")
    if offenders:
        print("[WARN] Columna 'source' encontrada en:")
        for p in offenders:
            print(f"  - {p}")

    dfs = []
    for path in paths:
        try:
            dfs.append(pd.read_parquet(path))
        except Exception as exc:
            print(f"[WARN] No se pudo leer {path}: {exc}")
    if not dfs:
        raise FileNotFoundError("No se pudieron cargar features del rango solicitado.")

    df = pd.concat(dfs, ignore_index=True)
    return df


def _write_ticker_summary(trades_rows: list[dict], out_dir: Path) -> None:
    flat = pd.DataFrame(trades_rows) if trades_rows else pd.DataFrame()
    if flat.empty or "ticker" not in flat.columns:
        return
    rows = []
    for ticker, group in flat.groupby("ticker"):
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
    path = out_dir / "backtest_ticker_summary.json"
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def resolve_date_range(args) -> tuple[datetime, datetime]:
    if args.start_date or args.end_date:
        if not (args.start_date and args.end_date):
            raise ValueError("start-date y end-date deben especificarse juntos")
        start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d")
        return start_date, end_date

    if args.date:
        end_date = datetime.strptime(args.date, "%Y-%m-%d")
    else:
        latest_path = get_latest_features_path(FEATURES_BASE)
        end_date = _date_from_features_path(latest_path)
    start_date = end_date - timedelta(days=args.lookback_days)
    return start_date, end_date


def main():
    try:
        parser = argparse.ArgumentParser(description="Backtest basado en features consolidados.")
        parser.add_argument("--date", type=str, help="Fecha en formato YYYY-MM-DD")
        parser.add_argument("--lookback-days", type=int, default=252)
        parser.add_argument("--start-date", type=str, help="Fecha inicio YYYY-MM-DD")
        parser.add_argument("--end-date", type=str, help="Fecha fin YYYY-MM-DD")
        parser.add_argument("--eval-mode", choices=["oos_holdout", "in_sample"], default="oos_holdout")
        args = parser.parse_args()

        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)

        np.random.seed(cfg["SEED"])
        OUT_DIR.mkdir(parents=True, exist_ok=True)

        start_date, end_date = resolve_date_range(args)
        features_df = load_features_range(start_date, end_date)
        oos_meta = {
            "evaluation_mode": args.eval_mode,
            "train_start_date": None,
            "train_end_date": None,
            "purge_start_date": None,
            "purge_end_date": None,
            "test_start_date": start_date.strftime("%Y-%m-%d"),
            "test_end_date": end_date.strftime("%Y-%m-%d"),
        }
        model_ref = MODEL_PATH
        feature_count = None

        if args.eval_mode == "oos_holdout":
            train_df, eval_df, oos_meta = split_oos_by_date(features_df)
            model_ref, selected_features = train_intraday_oos_model(train_df)
            feature_count = len(selected_features)
            features_df = eval_df
            print("[BACKTEST] evaluation_mode=oos_holdout")
            print(
                f"[BACKTEST] train={oos_meta['train_start_date']}..{oos_meta['train_end_date']} "
                f"purge={oos_meta['purge_start_date']}..{oos_meta['purge_end_date']} "
                f"test={oos_meta['test_start_date']}..{oos_meta['test_end_date']}"
            )
            print(f"[BACKTEST] rows train={len(train_df)} test={len(eval_df)} selected_features={feature_count}")
        else:
            print("[BACKTEST] evaluation_mode=in_sample")

        df = prepare_data(
            features_path=features_df,
            model_path=model_ref,
            clip_ret=cfg["CLIP_RET"],
            stop_loss=cfg["STOP_LOSS"],
            take_profit=cfg["TAKE_PROFIT"]
        )

        capital_log, daily_ret, trades_rows, day_dates = run_backtest(df, cfg)

        summary, metrics = compute_metrics(capital_log, daily_ret, trades_rows, day_dates, OUT_DIR, cfg)
        summary_path = OUT_DIR / "backtest_summary.json"
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        payload.update(oos_meta)
        payload["target_definition"] = "signal_at_close_t__enter_open_t_plus_1__exit_close_t_plus_1"
        if feature_count is not None:
            payload["selected_features_count"] = int(feature_count)
        payload["evaluated_rows"] = int(len(df))
        summary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        _write_ticker_summary(trades_rows, OUT_DIR)

        plot_equity_curve(summary, OUT_DIR / "equity_curve_realistic.png")

        print("Resultados del backtest:")
        print(f"- Retorno total: {metrics['ret_total']:.4f}")
        print(f"- Retorno promedio diario: {metrics['ret_daily_mean']:.5f}")
        print(f"- Max. drawdown: {metrics['max_drawdown']:.2%}")
        print(f"- Cantidad de operaciones: {metrics['operations']}")
        print(f"Guardado en: {OUT_DIR}")

    except Exception as e:
        print("Error durante el backtest:")
        print(f"{type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        exit(1)


if __name__ == "__main__":
    main()

