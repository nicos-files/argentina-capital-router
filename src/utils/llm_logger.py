import os
import pandas as pd
import json
from datetime import datetime

LOG_DIR = "data/logs"
os.makedirs(LOG_DIR, exist_ok=True)

def log_llm_interaction(entry: dict, log_name: str = "llm_interactions"):
    """
    Guarda una entrada de interacción con el LLM en un archivo .parquet rotado por fecha.

    Parámetros:
    - entry: dict con los campos a guardar
    - log_name: nombre base del archivo (sin extensión)
    """
    # Agregar timestamp si no está
    if "timestamp" not in entry:
        entry["timestamp"] = datetime.now().isoformat()

    # Serializar 'msg' si es dict
    if "msg" in entry:
        entry["msg"] = json.dumps(entry["msg"]) if isinstance(entry["msg"], dict) else str(entry["msg"])

    # Generar nombre de archivo con fecha
    date_str = datetime.now().strftime("%Y-%m-%d")
    log_file = os.path.join(LOG_DIR, f"{log_name}_{date_str}.parquet")

    try:
        df = pd.DataFrame([entry])
        if os.path.exists(log_file):
            df_existing = pd.read_parquet(log_file)
            # Filtrar DataFrames vacíos o sin columnas útiles
            frames = [df_existing, df]
            frames = [f for f in frames if not f.empty and not f.isna().all(axis=1).all()]    
            df = pd.concat(frames, ignore_index=True)
        df.to_parquet(log_file, index=False)
    except Exception as e:
        # Fallback a CSV si falla parquet
        fallback_file = os.path.join(LOG_DIR, f"{log_name}_{date_str}_fallback.csv")
        print(f"[WARN] Falló escritura en Parquet: {e}. Guardando en CSV.")
        df.to_csv(fallback_file, mode="a", header=not os.path.exists(fallback_file), index=False)
