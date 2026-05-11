import pandas as pd
import joblib
from sklearn.model_selection import cross_val_score, TimeSeriesSplit
from sklearn.metrics import accuracy_score, mean_squared_error, r2_score
from pathlib import Path
from datetime import datetime
import argparse
import numpy as np

def parse_args():
    parser = argparse.ArgumentParser(description="Valida modelos entrenados.")
    parser.add_argument("--date", type=str, help="Fecha en formato YYYY-MM-DD")
    return parser.parse_args()

args = parse_args()
date = args.date or datetime.today().strftime("%Y-%m-%d")

# Paths
features_path = Path(f"data/processed/features/{date[:4]}/{date[5:7]}/{date[8:]}/features.parquet")
model_dir = Path("models")

if not features_path.exists():
    raise FileNotFoundError(f"No se encontró el archivo de features: {features_path}")

df = pd.read_parquet(features_path)

# Targets
targets = {
    "xgb_clf_actual.pkl": "target_clasificacion",
    "xgb_clf_futuro.pkl": "target_clasificacion_t+1",
    "xgb_reg_actual.pkl": "daily_return",
    "xgb_reg_futuro.pkl": "target_regresion_t+1"
}

drop_cols = [
    "ticker", "timestamp_proceso", "timestamp_ejecucion",
    "target_clasificacion", "target_clasificacion_t+1",
    "daily_return", "target_regresion_t+1",
    "sentimiento_especifico", "sentimiento_general"
]

def select_relevant_features(df, target_col, threshold_var=1e-5, max_null_pct=0.3):
    numeric = df.select_dtypes(include="number")
    stds = numeric.std()
    null_pct = numeric.isnull().mean()
    return [
        col for col in numeric.columns
        if stds[col] > threshold_var and null_pct[col] < max_null_pct and col != target_col
    ]

def validate_model(model_path, target_col):
    print(f"\n Validando modelo: {model_path.name}")
    model = joblib.load(model_path)
    df_model = df.dropna(subset=[target_col])
    y = df_model[target_col]
    
    # Excluir columnas solo para features, pero mantener 'ticker' en df_model
    feature_exclude = [col for col in drop_cols if col != target_col and col != "ticker"]
    df_features = df_model.drop(columns=[col for col in feature_exclude if col in df_model.columns])
    
    selected_features = select_relevant_features(df_features, target_col)
    X = df_features[selected_features].fillna(0)


    # Validación cruzada
    if "clf" in model_path.name:
        scores = cross_val_score(model, X, y, cv=5, scoring="accuracy")
        print(f" Accuracy CV: {scores.mean():.4f} ± {scores.std():.4f}")
    else:
        scores = cross_val_score(model, X, y, cv=5, scoring="r2")
        print(f" R² CV: {scores.mean():.4f} ± {scores.std():.4f}")

    # Validación temporal
    print(" Validación temporal (TimeSeriesSplit):")
    tscv = TimeSeriesSplit(n_splits=5)
    temporal_scores = []
    for train_idx, test_idx in tscv.split(X):
        X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
        y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]
        model.fit(X_train, y_train)
        y_pred = model.predict(X_test)
        if "clf" in model_path.name:
            score = accuracy_score(y_test, y_pred)
        else:
            score = r2_score(y_test, y_pred)
        temporal_scores.append(score)
    print(f" Temporal CV: {np.mean(temporal_scores):.4f} ± {np.std(temporal_scores):.4f}")

    # Validación por ticker
    print(" Validación por ticker:")
    for ticker in df_model["ticker"].unique():
        subset = df_model[df_model["ticker"] == ticker]
        X_sub = subset[selected_features].fillna(0)
        y_sub = subset[target_col]
        if len(X_sub) < 10:
            continue
        score = model.score(X_sub, y_sub)
        print(f" {ticker}: {score:.4f}")

for model_file, target_col in targets.items():
    model_path = model_dir / model_file
    if model_path.exists():
        validate_model(model_path, target_col)
    else:
        print(f" Modelo no encontrado: {model_file}")
