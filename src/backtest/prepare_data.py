import pandas as pd
import numpy as np
import joblib
from pathlib import Path


def prepare_data(features_path, model_path, clip_ret, stop_loss, take_profit):
    if isinstance(features_path, pd.DataFrame):
        df = features_path.copy()
    else:
        df = pd.read_parquet(features_path)

    target_cols = ["target_regresion_t+1", "target_clasificacion_t+1"]
    missing_targets = [c for c in target_cols if c not in df.columns]
    if missing_targets:
        raise ValueError(f"Faltan columnas de target: {missing_targets}")

    # Validar indice temporal
    if isinstance(df.index, pd.DatetimeIndex):
        idx = pd.to_datetime(df.index, errors="coerce").normalize()

        if "date" in df.columns:
            # Si ya existe 'date' como columna, priorizamos esa y normalizamos
            df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
        else:
            df = df.copy()
            df["date"] = idx

    # Caso B: NO viene con DatetimeIndex -> armamos 'date' desde columnas
    else:
        if "timestamp_proceso" in df.columns:
            df["timestamp_proceso"] = pd.to_datetime(df["timestamp_proceso"], errors="coerce")
            df["date"] = df["timestamp_proceso"].dt.normalize()
        elif "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
        else:
            raise ValueError("No se encontro un indice temporal valido (index, timestamp_proceso o date).")

    # Validaciones
    if df["date"].isna().any():
        bad = int(df["date"].isna().sum())
        raise ValueError(f"prepare_data: {bad} filas con date=NaT tras parsing/normalizacion.")

    # Validar que NO haya columnas duplicadas (detecta doble origen/merge)
    if df.columns.duplicated().any():
        dups = df.columns[df.columns.duplicated()].tolist()
        raise ValueError(f"prepare_data: columnas duplicadas detectadas (probable doble origen/merge): {dups}")

    # Validar ticker
    if "ticker" not in df.columns:
        raise ValueError("El dataset no tiene columna 'ticker'.")
    df["ticker"] = df["ticker"].astype(str)
    

    print("=== prepare_data DEBUG ===")
    print("df shape:", df.shape)

    dup_labels = df.columns[df.columns.duplicated()].tolist()
    print("duplicated labels:", dup_labels)

    print("date label count:", (df.columns == "date").sum())
    print("first 80 cols:", df.columns.tolist()[:80])

    # si querés ver TODAS:
    # print("ALL cols:", df.columns.tolist())

    print("==========================")


    df = df.sort_values(["date", "ticker"])
    df = df.drop_duplicates(subset=["date", "ticker"], keep="last")

    # Evitar colapso por t+1 NaN: drop solo ultima fila por ticker si corresponde
    last_dates = df.groupby("ticker")["date"].transform("max")
    is_last = df["date"] == last_dates
    na_mask = df[target_cols].isna().any(axis=1)
    drop_last = na_mask & is_last
    if drop_last.any():
        df = df[~drop_last].copy()

    remaining_na = df[target_cols].isna().any(axis=1)
    if remaining_na.any():
        print("[BACKTEST] Warning: rows con NaN en targets fuera del ultimo dia, se descartaran")
        df = df[~remaining_na].copy()

    df = df.set_index(["date", "ticker"]).sort_index()

    drop_cols = [
        "ticker",
        "timestamp_ejecucion",
        "timestamp_proceso",
        "date",
        "daily_return",
        "target_clasificacion",
        "target_regresion_t+1",
        "target_clasificacion_t+1",
        "sentimiento_especifico",
        "sentimiento_general",
    ]

    X = df.drop(columns=[c for c in drop_cols if c in df.columns], errors="ignore").copy()

    datetime_cols = [c for c in X.columns if pd.api.types.is_datetime64_any_dtype(X[c])]
    timedelta_cols = [c for c in X.columns if pd.api.types.is_timedelta64_dtype(X[c])]
    if datetime_cols or timedelta_cols:
        print(f"[BACKTEST] Dropping datetime/timedelta columns from X: {datetime_cols + timedelta_cols}")
        X = X.drop(columns=datetime_cols + timedelta_cols)

    for col in X.columns:
        if not pd.api.types.is_numeric_dtype(X[col]):
            X[col] = pd.to_numeric(X[col], errors="coerce")

    if isinstance(model_path, (str, Path)):
        model = joblib.load(model_path)
    else:
        model = model_path
    expected_features = model.get_booster().feature_names

    missing = [col for col in expected_features if col not in X.columns]
    if missing:
        raise ValueError(f"Faltan columnas requeridas por el modelo: {missing}")

    X = X[expected_features]
    print(f"[BACKTEST] Model features: {list(X.columns)}")

    df["prediccion"] = model.predict(X)
    if hasattr(model, "predict_proba"):
        df["proba"] = model.predict_proba(X)[:, 1]

    df["ret_adj"] = (
        df["target_regresion_t+1"]
        .clip(lower=-clip_ret, upper=clip_ret)
        .clip(lower=-stop_loss, upper=take_profit)
    )

    return df
