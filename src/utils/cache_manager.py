# src/utils/cache_manager.py

import os
from pathlib import Path
import pandas as pd
import hashlib
import re




CACHE_PATH = "data/cache"
os.makedirs(CACHE_PATH, exist_ok=True)


def normalizar_texto(texto: str) -> str:
    texto = texto.lower()
    texto = re.sub(r"[^\w\s]", "", texto)  # elimina puntuación
    texto = re.sub(r"\s+", " ", texto).strip()  # normaliza espacios
    return texto

def hash_text(text: str) -> str:
    texto_norm = normalizar_texto(text)
    return hashlib.md5(texto_norm.encode("utf-8")).hexdigest()


def _resolve_cache_path(cache_file) -> str:
    if isinstance(cache_file, Path):
        return str(cache_file)
    if isinstance(cache_file, str) and (os.sep in cache_file or cache_file.startswith(".")):
        return cache_file
    return os.path.join(CACHE_PATH, cache_file)

def load_cache(cache_file) -> dict:
    path = _resolve_cache_path(cache_file)
    if os.path.exists(path):
        df = pd.read_parquet(path)
        return dict(zip(df["hash"], df["respuesta"]))
    return {}

def save_to_cache(cache_file, nuevos: list):
    path = _resolve_cache_path(cache_file)
    df_nuevos = pd.DataFrame(nuevos)
    if os.path.exists(path):
        df_existente = pd.read_parquet(path)
        df_total = pd.concat([df_existente, df_nuevos], ignore_index=True)
    else:
        df_total = df_nuevos
    df_total.to_parquet(path, index=False)
