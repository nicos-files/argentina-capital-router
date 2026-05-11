import os
import sys
import time
import argparse
import pandas as pd
from datetime import datetime
from pathlib import Path
from textblob import TextBlob
import re

from dotenv import load_dotenv

# Cargar .env desde la raíz del proyecto
PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")

# Asegurar que OPENAI_API_KEY quede disponible para imports posteriores
api_key = os.getenv("OPENAI_API_KEY")
if api_key:
    os.environ["OPENAI_API_KEY"] = api_key


def clean_text(texto: str) -> str:
    # Elimina emojis y caracteres fuera del rango ASCII
    return re.sub(r'[^\x00-\x7F]+', '', texto)



from src.agents.agent_definitions import sentiment_agent
from src.utils.llm_logger import log_llm_interaction
from src.utils.cache_manager import hash_text, load_cache, save_to_cache
from src.utils.execution_context import (
    get_execution_date,
    get_execution_hour
)
ROOT = Path(__file__).resolve().parents[3]
# =========================
# CONFIGURACIÓN
# =========================
RAW_PATH = ROOT / "data" / "raw" / "sentiment"
RELEVANT_PATH = ROOT / "data" / "processed" / "sentiment" / "relevant"
DEBUG_PATH = ROOT / "data" / "debug"
CACHE_PATH = ROOT / "data" / "cache"
CACHE_FILE = "relevance_cache.parquet"
INDEX_PATH = ROOT / "data" / "indexes" / "sentiment_index.csv"


RELEVANT_PATH.mkdir(parents=True, exist_ok=True)
DEBUG_PATH.mkdir(parents=True, exist_ok=True)
INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)

# =========================
# CARGA DE ESTADO
# =========================
cache_path = CACHE_PATH / CACHE_FILE
cache = load_cache(cache_path)
nuevos_cache = []
relevance_index = []
textos_descartados = []
resumen_fuentes = []

def load_index_hashes(index_path):
    if index_path.exists():
        try:
            df = pd.read_csv(index_path)
            return set(df["hash"].dropna().unique())
        except Exception:
            return set()
    return set()

hashes_evaluados = load_index_hashes(INDEX_PATH)

# =========================
# FUNCIÓN PRINCIPAL
# =========================

def es_relevante(texto: str) -> bool:
    if not isinstance(texto, str) or not texto.strip():
        print(" Texto vacío o inválido, se descarta.")
        return False

    h = hash_text(texto)

    if h in cache:
        print(f" Cache hit  texto ya evaluado.")
        resp_cache = cache[h].strip().lower()
        resp_cache_norm = (
            resp_cache.replace(".", "").replace("!", "").replace("¡", "")
            .replace("?", "").replace("¿", "").replace("si", "sí").strip()
        )
        print(f" Respuesta desde cache: {resp_cache_norm}")
        return resp_cache_norm == "sí"

    if h in hashes_evaluados:
        print(f" Ya evaluado previamente hash: {h}")
        return False

    start_time = time.time()

    try:
        prompt = clean_text(texto)  # si usás un prompt más elaborado, reemplazalo acá
        print(f"\n Evaluando texto:\n {prompt}\n")

        respuesta_raw = sentiment_agent.relevance_filter(prompt).strip().lower()
        respuesta_norm = (
            respuesta_raw.replace(".", "").replace("!", "").replace("¡", "")
            .replace("?", "").replace("¿", "").replace("si", "sí").strip()
        )

        es_ok = respuesta_norm in ["sí", "no"]
        estado = " ok" if es_ok else " ambiguo"
        elapsed = round(time.time() - start_time, 3)

        print(f" Respuesta LLM: {respuesta_raw}")
        print(f" Normalizada: {respuesta_norm}")
        print(f" Estado: {estado} | Tiempo: {elapsed}s")
        print(f" Relevante: {' Sí' if respuesta_norm == 'sí' else ' No'}")

    except Exception as e:
        elapsed = round(time.time() - start_time, 3)
        print(f" Error al invocar el modelo: {str(e)}")
        textos_descartados.append(texto)
        return False

    if h not in cache:
        nuevos_cache.append({"hash": h, "texto": texto, "respuesta": respuesta_norm})

    relevance_index.append({
        "hash": h,
        "texto": texto,
        "respuesta_llm": respuesta_raw,
        "es_relevante": respuesta_norm == "sí",
        "modelo": getattr(sentiment_agent, "relevance_model", "desconocido"),
        "timestamp": datetime.now().isoformat()
    })

    if not es_ok or respuesta_norm != "sí":
        textos_descartados.append(texto)
        return False

    return True


def filtrar_fuente(path: Path):
    if not path.exists():
        print(f"Archivo no encontrado: {path}")
        return

    start_time = time.time()
    df = pd.read_parquet(path)
    columna = "title" if "title" in df.columns else "text"
    df["texto"] = df[columna].astype(str)
    df["es_relevante"] = df["texto"].apply(es_relevante)
    df_relevante = df[df["es_relevante"]]

    #rel_path = path.relative_to(RAW_PATH)
    #out_path = RELEVANT_PATH / rel_path
    #out_path.parent.mkdir(parents=True, exist_ok=True)
    ticker = path.parts[-6]
    fuente = path.stem.split('_')[-1]
    nombre_archivo = f"{ticker}_{fuente}.parquet"
    fecha_rel = Path(f"{date.year:04d}/{date.month:02d}/{date.day:02d}")
    if hour:
        fecha_rel = fecha_rel / hour
    out_path = RELEVANT_PATH / fecha_rel / nombre_archivo
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df_relevante.to_parquet(out_path, index=False)

    elapsed = round(time.time() - start_time, 2)
    total = len(df)
    relevantes = len(df_relevante)
    porcentaje = round((relevantes / total) * 100, 2) if total > 0 else 0.0

    resumen_fuentes.append({
        "archivo": str(out_path),
        "total_textos": total,
        "textos_relevantes": relevantes,
        "porcentaje_relevantes": porcentaje,
        "tiempo_total_segundos": elapsed,
        "modelo_usado": getattr(sentiment_agent, "relevance_model", "desconocido")
    })

    print(f" {out_path}: {total} originales, {relevantes} relevantes ({porcentaje}%)")

# =========================
# EJECUCIÓN PRINCIPAL
# =========================

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, help="Fecha en formato YYYY-MM-DD")
    parser.add_argument("--hour", type=str, help="Hora en formato HHMM")
    args = parser.parse_args()

    date = get_execution_date(args.date)
    hour = get_execution_hour(args.hour)

    archivos = []
    for ticker_dir in RAW_PATH.iterdir():
        fecha_dir = ticker_dir / f"{date.year:04d}" / f"{date.month:02d}" / f"{date.day:02d}"
        if hour:
            fecha_dir = fecha_dir / hour
        if fecha_dir.exists():
            archivos += list(fecha_dir.glob("*.parquet"))

    if not archivos:
        print(" No hay archivos para procesar en la fecha/hora indicada.")
        exit()

    for archivo in archivos:
        filtrar_fuente(archivo)

    if textos_descartados:
        pd.DataFrame({"texto": textos_descartados}).to_parquet(
            DEBUG_PATH / "textos_descartados_llm.parquet", index=False
        )

    revisados = []
    for texto in textos_descartados:
        try:
            blob = TextBlob(texto)
            polarity = blob.sentiment.polarity
            if abs(polarity) > 0.3:
                revisados.append({"texto": texto, "polarity": polarity})
        except Exception:
            continue

    if revisados:
        pd.DataFrame(revisados).to_parquet(
            DEBUG_PATH / "textos_revisados_por_textblob.parquet", index=False
        )
        print(f" Se guardaron {len(revisados)} textos con sentimiento fuerte descartados por el LLM")
    else:
        print(" No se detectaron textos descartados con polaridad fuerte")

    if resumen_fuentes:
        df_resumen = pd.DataFrame(resumen_fuentes)
        df_resumen.to_parquet(DEBUG_PATH / "resumen_relevancia_por_fuente.parquet", index=False)
        print(" Resumen por fuente guardado en DEBUG_PATH")

    save_to_cache(cache_path, nuevos_cache)
    print(f" Cache actualizado con {len(nuevos_cache)} nuevas entradas.")

    if relevance_index:
        df_index = pd.DataFrame(relevance_index)
        if INDEX_PATH.exists():
            prev = pd.read_csv(INDEX_PATH)
            df_index = pd.concat([prev, df_index]).drop_duplicates(subset=["hash"])
        df_index.to_csv(INDEX_PATH, index=False)
        print(f" Índice de relevancia actualizado con {len(relevance_index)} entradas nuevas.")
