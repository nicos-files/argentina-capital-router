from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import classification_report, confusion_matrix, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split

sys.path.append("C:/Users/NAguilar/Proyectos/AutoGen/quant-trading-bot")

from src.utils.execution_context import get_execution_date
from src.utils.llm_logger import log_llm_interaction


FEATURES_BASE = Path("data/processed/features")
MODELS_DIR = Path("models")
MIN_TARGET_ROWS = 50
MIN_FILE_TARGET_ROWS = 1
TRAIN_LOOKBACK_DAYS = 252
DROP_COLS = [
    "ticker",
    "timestamp_proceso",
    "timestamp_ejecucion",
    "target_clasificacion",
    "target_clasificacion_t+1",
    "target_clasificacion_t+5",
    "daily_return",
    "target_regresion_t+1",
    "target_regresion_t+5",
    "sentimiento_especifico",
    "sentimiento_general",
]
CLASSIFICATION_TARGETS = {
    "actual": "target_clasificacion",
    "futuro": "target_clasificacion_t+1",
    "long_term": "target_clasificacion_t+5",
}
REGRESSION_TARGETS = {
    "actual": "daily_return",
    "futuro": "target_regresion_t+1",
    "long_term": "target_regresion_t+5",
}
MODEL_ALIASES = {
    ("clf", "futuro"): ["xgb_clf_intraday.pkl"],
    ("clf", "long_term"): ["xgb_clf_long_term.pkl"],
    ("reg", "futuro"): ["xgb_reg_intraday.pkl"],
    ("reg", "long_term"): ["xgb_reg_long_term.pkl"],
}


def _iter_feature_candidates(base_path: Path = FEATURES_BASE) -> list[tuple[datetime, Path]]:
    candidates: list[tuple[datetime, Path]] = []
    for candidate in base_path.glob("*/*/*/features.parquet"):
        if not candidate.exists():
            continue
        try:
            rel = candidate.relative_to(base_path)
            date = datetime.strptime("/".join(rel.parts[:3]), "%Y/%m/%d")
        except Exception:
            continue
        candidates.append((date, candidate))
    return sorted(candidates, key=lambda item: item[0], reverse=True)


def resolve_features_path(
    requested_date: str | None,
    required_targets: list[str] | None = None,
    min_target_rows: int = MIN_FILE_TARGET_ROWS,
    base_path: Path = FEATURES_BASE,
) -> tuple[datetime, Path]:
    candidates = _iter_feature_candidates(base_path)
    if not candidates:
        raise FileNotFoundError("No se encontró ningún archivo consolidado de features.")

    if requested_date:
        requested = get_execution_date(requested_date)
        candidates = [(date, path) for date, path in candidates if date <= requested]
        if not candidates:
            raise FileNotFoundError(
                f"No se encontró ningún archivo de features en o antes de {requested_date}."
            )

    if not required_targets:
        return candidates[0]

    missing_errors: list[str] = []
    for date, path in candidates:
        try:
            target_df = pd.read_parquet(path, columns=required_targets)
        except Exception as exc:
            missing_errors.append(f"{date.strftime('%Y-%m-%d')}: {exc}")
            continue
        if any(col not in target_df.columns for col in required_targets):
            continue
        if all(int(target_df[col].notna().sum()) >= min_target_rows for col in required_targets):
            return date, path

    raise FileNotFoundError(
        "No se encontró ningún archivo de features con targets disponibles "
        f"para {required_targets} en o antes de {requested_date or 'latest'}."
        + (f" Últimos errores: {missing_errors[-3:]}" if missing_errors else "")
    )


def select_relevant_features(
    df: pd.DataFrame,
    target_col: str,
    threshold_var: float = 1e-5,
    max_null_pct: float = 0.3,
) -> list[str]:
    numeric = df.select_dtypes(include="number")
    stds = numeric.std().fillna(0.0)
    null_pct = numeric.isnull().mean().fillna(1.0)
    return [
        col
        for col in numeric.columns
        if stds[col] > threshold_var and null_pct[col] < max_null_pct and col != target_col
    ]


def time_split_indices(df: pd.DataFrame, test_size: float = 0.3, time_col: str = "timestamp_proceso"):
    if time_col not in df.columns:
        return None
    df_sorted = df.sort_values(time_col)
    split_idx = int(len(df_sorted) * (1 - test_size))
    return df_sorted.index[:split_idx], df_sorted.index[split_idx:]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Entrena modelos usando features diarios.")
    parser.add_argument("--date", type=str, help="Fecha en formato YYYY-MM-DD")
    return parser.parse_args()


def _load_frame_cached(cache: dict[Path, pd.DataFrame], path: Path) -> pd.DataFrame:
    frame = cache.get(path)
    if frame is None:
        frame = pd.read_parquet(path)
        cache[path] = frame
    return frame.copy()


def _load_training_dataset(
    requested_date: str | None,
    target_col: str,
    lookback_days: int = TRAIN_LOOKBACK_DAYS,
    base_path: Path = FEATURES_BASE,
    cache: dict[Path, pd.DataFrame] | None = None,
) -> tuple[datetime, Path, pd.DataFrame, int]:
    end_date, end_path = resolve_features_path(
        requested_date=requested_date,
        required_targets=[target_col],
        min_target_rows=MIN_FILE_TARGET_ROWS,
        base_path=base_path,
    )
    start_date = end_date - pd.Timedelta(days=lookback_days)
    cache = cache or {}
    frames: list[pd.DataFrame] = []
    files_used = 0

    for date, path in sorted(_iter_feature_candidates(base_path), key=lambda item: item[0]):
        if date < start_date or date > end_date:
            continue
        try:
            target_df = pd.read_parquet(path, columns=[target_col])
        except Exception:
            continue
        if target_col not in target_df.columns:
            continue
        if int(target_df[target_col].notna().sum()) < MIN_FILE_TARGET_ROWS:
            continue
        frame = _load_frame_cached(cache, path)
        if target_col not in frame.columns:
            continue
        frames.append(frame)
        files_used += 1

    if not frames:
        raise FileNotFoundError(
            f"No se encontraron features históricos utilizables para {target_col} "
            f"en la ventana {start_date.strftime('%Y-%m-%d')}..{end_date.strftime('%Y-%m-%d')}."
        )

    dataset = pd.concat(frames, ignore_index=True)
    return end_date, end_path, dataset, files_used


def _build_feature_matrix(df_model: pd.DataFrame, target_col: str) -> tuple[pd.DataFrame, pd.Series, list[str]]:
    feature_df = df_model.drop(
        columns=[col for col in DROP_COLS if col in df_model.columns and col != target_col],
        errors="ignore",
    )
    selected = select_relevant_features(feature_df, target_col)
    if not selected:
        raise ValueError(f"No hay features seleccionables para {target_col}")
    X_all = feature_df[selected].fillna(0)
    y_all = df_model[target_col]
    return X_all, y_all, selected


def _write_feature_importance(model: Any, columns: list[str], output_path: Path, title: str, color: str) -> None:
    importance = model.feature_importances_
    sorted_idx = np.argsort(importance)[::-1]
    top_columns = np.asarray(columns)[sorted_idx][:20][::-1]
    top_importance = importance[sorted_idx][:20][::-1]

    plt.figure(figsize=(10, 6))
    plt.barh(top_columns, top_importance, color=color)
    plt.xlabel("Importancia")
    plt.title(title)
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()


def _save_model(model: Any, family: str, label: str) -> Path:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODELS_DIR / f"xgb_{family}_{label}.pkl"
    joblib.dump(model, model_path)
    print(f" Modelo guardado: {model_path.as_posix()}")
    for alias_name in MODEL_ALIASES.get((family, label), []):
        alias_path = MODELS_DIR / alias_name
        joblib.dump(model, alias_path)
        print(f" Modelo guardado: {alias_path.as_posix()}")
    return model_path


def _train_classifier(
    df: pd.DataFrame,
    target_col: str,
    label: str,
    source_date: datetime,
    source_path: Path,
) -> None:
    print(f"\n Clasificación: {target_col}")
    print(f" [INFO] source_date={source_date.strftime('%Y-%m-%d')} source_path={source_path}")
    start = time.time()
    log_entry: dict[str, Any] = {
        "timestamp": datetime.now(),
        "module": "train_model",
        "tipo": "clasificacion",
        "target": target_col,
        "source_date": source_date.strftime("%Y-%m-%d"),
        "source_path": str(source_path),
    }

    try:
        if target_col not in df.columns:
            print(f" [WARN] Target ausente, se saltea: {target_col}")
            return

        df_model = df.dropna(subset=[target_col]).copy()
        if len(df_model) < MIN_TARGET_ROWS:
            print(f" [WARN] Target con pocas filas ({len(df_model)}), se saltea: {target_col}")
            return

        X_all, y_all, selected_features = _build_feature_matrix(df_model, target_col)
        log_entry["selected_features"] = selected_features

        split_idx = time_split_indices(df_model, test_size=0.3)
        if split_idx:
            train_idx, test_idx = split_idx
            X_train, X_test = X_all.loc[train_idx], X_all.loc[test_idx]
            y_train, y_test = y_all.loc[train_idx], y_all.loc[test_idx]
        else:
            X_train, X_test, y_train, y_test = train_test_split(
                X_all, y_all, test_size=0.3, random_state=42
            )

        model = xgb.XGBClassifier(use_label_encoder=False, eval_metric="logloss", random_state=42)
        model.fit(X_train, y_train)
        y_pred = model.predict(X_test)

        print(f"\n Reporte de clasificación ({label}):")
        print(classification_report(y_test, y_pred))
        print(" Matriz de confusión:")
        print(confusion_matrix(y_test, y_pred))

        model_path = _save_model(model, "clf", label)
        _write_feature_importance(
            model=model,
            columns=list(X_all.columns),
            output_path=MODELS_DIR / f"feature_importance_clf_{label}.png",
            title=f"Top 20 Features ({label} - Clasificación)",
            color="skyblue",
        )

        duration = time.time() - start
        log_entry.update(
            {
                "status": "ok",
                "duration_sec": round(duration, 2),
                "accuracy": float((y_pred == y_test).mean()),
                "modelo_path": str(model_path),
            }
        )
    except Exception as exc:
        log_entry.update({"status": "error", "error_msg": str(exc)})
        raise
    finally:
        log_llm_interaction(log_entry, log_name="train_model")


def _train_regressor(
    df: pd.DataFrame,
    target_col: str,
    label: str,
    source_date: datetime,
    source_path: Path,
) -> None:
    print(f"\n Regresión: {target_col}")
    print(f" [INFO] source_date={source_date.strftime('%Y-%m-%d')} source_path={source_path}")
    start = time.time()
    log_entry: dict[str, Any] = {
        "timestamp": datetime.now(),
        "module": "train_model",
        "tipo": "regresion",
        "target": target_col,
        "source_date": source_date.strftime("%Y-%m-%d"),
        "source_path": str(source_path),
    }

    try:
        if target_col not in df.columns:
            print(f" [WARN] Target ausente, se saltea: {target_col}")
            return

        df_model = df.dropna(subset=[target_col]).copy()
        if len(df_model) < MIN_TARGET_ROWS:
            print(f" [WARN] Target con pocas filas ({len(df_model)}), se saltea: {target_col}")
            return

        X_all, y_all, selected_features = _build_feature_matrix(df_model, target_col)
        log_entry["selected_features"] = selected_features

        split_idx = time_split_indices(df_model, test_size=0.3)
        if split_idx:
            train_idx, test_idx = split_idx
            X_train, X_test = X_all.loc[train_idx], X_all.loc[test_idx]
            y_train, y_test = y_all.loc[train_idx], y_all.loc[test_idx]
        else:
            X_train, X_test, y_train, y_test = train_test_split(
                X_all, y_all, test_size=0.3, random_state=42
            )

        model = xgb.XGBRegressor(objective="reg:squarederror", n_estimators=100, random_state=42)
        model.fit(X_train, y_train)
        y_pred = model.predict(X_test)

        rmse = float(np.sqrt(mean_squared_error(y_test, y_pred)))
        r2 = float(r2_score(y_test, y_pred))

        print(f"\n Reporte de regresión ({label}):")
        print(f" RMSE: {rmse:.5f}")
        print(f" R² Score: {r2:.5f}")

        model_path = _save_model(model, "reg", label)
        _write_feature_importance(
            model=model,
            columns=list(X_all.columns),
            output_path=MODELS_DIR / f"feature_importance_reg_{label}.png",
            title=f"Top 20 Features ({label} - Regresión)",
            color="salmon",
        )

        duration = time.time() - start
        log_entry.update(
            {
                "status": "ok",
                "duration_sec": round(duration, 2),
                "rmse": round(rmse, 5),
                "r2_score": round(r2, 5),
                "modelo_path": str(model_path),
            }
        )
    except Exception as exc:
        log_entry.update({"status": "error", "error_msg": str(exc)})
        raise
    finally:
        log_llm_interaction(log_entry, log_name="train_model")


def train_models(requested_date: str | None = None) -> None:
    if requested_date:
        print(f"[INFO] Fecha solicitada: {requested_date}")
    else:
        latest_date, _ = resolve_features_path(None)
        print(f"[INFO] Usando última fecha disponible: {latest_date.strftime('%Y-%m-%d')}")

    cache: dict[Path, pd.DataFrame] = {}
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    for label, target_col in CLASSIFICATION_TARGETS.items():
        try:
            source_date, source_path, frame, files_used = _load_training_dataset(
                requested_date=requested_date,
                target_col=target_col,
                cache=cache,
            )
        except FileNotFoundError as exc:
            print(f" [WARN] Target ausente en historial utilizable, se saltea {target_col}: {exc}")
            continue
        print(
            f" [INFO] dataset target={target_col} rows={len(frame)} files_used={files_used} "
            f"window_end={source_date.strftime('%Y-%m-%d')}"
        )
        _train_classifier(frame, target_col, label, source_date, source_path)

    for label, target_col in REGRESSION_TARGETS.items():
        try:
            source_date, source_path, frame, files_used = _load_training_dataset(
                requested_date=requested_date,
                target_col=target_col,
                cache=cache,
            )
        except FileNotFoundError as exc:
            print(f" [WARN] Target ausente en historial utilizable, se saltea {target_col}: {exc}")
            continue
        print(
            f" [INFO] dataset target={target_col} rows={len(frame)} files_used={files_used} "
            f"window_end={source_date.strftime('%Y-%m-%d')}"
        )
        _train_regressor(frame, target_col, label, source_date, source_path)


def main() -> None:
    args = parse_args()
    train_models(args.date)


if __name__ == "__main__":
    main()
