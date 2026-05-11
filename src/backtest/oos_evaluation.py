from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
import xgboost as xgb

from src.pipeline.train_model import DROP_COLS, select_relevant_features


TARGET_COL = "target_clasificacion_t+1"
DEFAULT_TEST_FRACTION = 0.3
DEFAULT_PURGE_DAYS = 1
MIN_TRAIN_DAYS = 60
MIN_TEST_DAYS = 20


def split_oos_by_date(
    df: pd.DataFrame,
    test_fraction: float = DEFAULT_TEST_FRACTION,
    purge_days: int = DEFAULT_PURGE_DAYS,
    min_train_days: int = MIN_TRAIN_DAYS,
    min_test_days: int = MIN_TEST_DAYS,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    if "date" not in df.columns and "timestamp_proceso" not in df.columns:
        raise ValueError("split_oos_by_date requiere columna 'date' o 'timestamp_proceso'")

    frame = df.copy()
    if "date" in frame.columns:
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    else:
        frame["date"] = pd.to_datetime(frame["timestamp_proceso"], errors="coerce").dt.normalize()

    frame = frame.dropna(subset=["date"]).sort_values(["date", "ticker"] if "ticker" in frame.columns else ["date"])
    unique_dates = sorted(pd.to_datetime(frame["date"]).drop_duplicates().tolist())
    if len(unique_dates) < (min_train_days + min_test_days + purge_days):
        raise ValueError(
            "Insuficientes fechas para evaluación OOS: "
            f"{len(unique_dates)} disponibles, se requieren al menos "
            f"{min_train_days + min_test_days + purge_days}."
        )

    split_idx = max(min_train_days, int(len(unique_dates) * (1.0 - test_fraction)))
    split_idx = min(split_idx, len(unique_dates) - min_test_days)
    train_end_idx = split_idx - purge_days
    if train_end_idx < min_train_days:
        raise ValueError("No hay suficientes fechas de train tras aplicar purge_days.")

    train_dates = unique_dates[:train_end_idx]
    purge_dates = unique_dates[train_end_idx:split_idx]
    test_dates = unique_dates[split_idx:]

    train_df = frame[frame["date"].isin(train_dates)].copy()
    test_df = frame[frame["date"].isin(test_dates)].copy()
    meta = {
        "evaluation_mode": "oos_holdout",
        "train_start_date": _fmt_date(train_dates[0]),
        "train_end_date": _fmt_date(train_dates[-1]),
        "purge_start_date": _fmt_date(purge_dates[0]) if purge_dates else None,
        "purge_end_date": _fmt_date(purge_dates[-1]) if purge_dates else None,
        "test_start_date": _fmt_date(test_dates[0]),
        "test_end_date": _fmt_date(test_dates[-1]),
        "train_days": len(train_dates),
        "test_days": len(test_dates),
        "purge_days": len(purge_dates),
    }
    return train_df, test_df, meta


def train_intraday_oos_model(train_df: pd.DataFrame, target_col: str = TARGET_COL) -> tuple[Any, list[str]]:
    if target_col not in train_df.columns:
        raise ValueError(f"Falta target para entrenar OOS: {target_col}")

    df_model = train_df.dropna(subset=[target_col]).copy()
    if df_model.empty:
        raise ValueError(f"Sin filas válidas para target {target_col}")

    feature_df = df_model.drop(
        columns=[col for col in DROP_COLS if col in df_model.columns and col != target_col],
        errors="ignore",
    )
    selected_features = select_relevant_features(feature_df, target_col)
    if not selected_features:
        raise ValueError(f"No hay features seleccionables para {target_col}")

    X_train = feature_df[selected_features].fillna(0)
    y_train = df_model[target_col]

    model = xgb.XGBClassifier(use_label_encoder=False, eval_metric="logloss", random_state=42)
    model.fit(X_train, y_train)
    return model, selected_features


def _fmt_date(value: datetime | pd.Timestamp) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d")
