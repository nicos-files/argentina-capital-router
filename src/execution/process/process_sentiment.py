import os
import sys
import re
import time
import argparse
import pandas as pd
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")

api_key = os.getenv("OPENAI_API_KEY")
if api_key:
    os.environ["OPENAI_API_KEY"] = api_key


from src.agents.agent_definitions import sentiment_agent
from src.utils.llm_logger import log_llm_interaction
from src.utils.execution_context import (
    get_execution_date,
    get_execution_hour,
    ensure_date_dir
)

ROOT = Path(__file__).resolve().parents[3]
RELEVANT_BASE = ROOT/"data"/"processed"/"sentiment"/"relevant"
PROCESSED_BASE = ROOT/"data"/"processed"/"sentiment"

def pick_text_column(df: pd.DataFrame) -> str:
    for c in ["texto", "title", "text", "description"]:
        if c in df.columns:
            return c
    raise ValueError(f"No se encontró columna de texto en columnas: {df.columns.tolist()}")

def extract_scores(response):
    response = response.replace(",", ".")
    matches = re.findall(r"-?\d+(?:\.\d+)?", response)

    if len(matches) >= 3:
        corto = float(matches[0])
        largo = float(matches[1])
        combinado = float(matches[2])
        return {
            "score_corto": max(min(corto, 1), -1),
            "score_largo": max(min(largo, 1), -1),
            "score_combinado": max(min(combinado, 1), -1)
        }
    return {"score_corto": None, "score_largo": None, "score_combinado": None}

def analyze_sentiment(text):
    #print(f"[DEBUG] Analizando texto: {text[:50]}...")
    if not text or not isinstance(text, str):
        return None

    start = time.time()
    try:
        response = sentiment_agent.process_sentiment(text)
    except Exception as e:
        print(f"Error al invocar el modelo: {e}")
        return None

    duration = time.time() - start
    response = response.strip()

    if not response:
        print(f"[ERROR] Modelo no devolvió respuesta para: {text[:50]}")
        return None

    scores = extract_scores(response)
    status = "ok" if scores and all(v is not None for v in scores.values()) else "error"

    log_entry = {
        "timestamp": datetime.now(),
        "module": "sentiment",
        "text": text,
        "response": response,
        "score_corto": scores.get("score_corto"),
        "score_largo": scores.get("score_largo"),
        "score_combinado": scores.get("score_combinado"),
        "duration_sec": round(duration, 2),
        "status": status
    }
    print("[DEBUG] Logueando interacción en llm_sentiment")
    log_llm_interaction(log_entry, log_name="llm_sentiment")

    if status == "error":
        print(f" Respuesta malformateada o incompleta: {response}")

    return {
    "score_corto": scores.get("score_corto", None),
    "score_largo": scores.get("score_largo", None),
    "score_combinado": scores.get("score_combinado", None)
    }


def process_general_sentiment(date, hour):
    dfs = []

    base_dir = RELEVANT_BASE / f"{date.year:04d}" / f"{date.month:02d}" / f"{date.day:02d}"
    if hour:
        base_dir = base_dir / hour

    print(f"[DEBUG] Buscando sentimiento general en: {base_dir}")

    if not base_dir.exists():
        print(" No existe carpeta de relevantes para el corte.")
        return None

    # economy_*.parquet (ej: economy_newsapi.parquet, economy_reddit.parquet)
    files = sorted(base_dir.glob("economy_*.parquet"))
    if not files:
        print(" No se encontraron archivos economy_*.parquet para sentimiento general")
        return None

    for path in files:
        df = pd.read_parquet(path)
        columna = pick_text_column(df)
        df_scores_series = df[columna].apply(analyze_sentiment)
        df_scores = pd.DataFrame([s for s in df_scores_series.tolist() if s is not None])

        # Si no hubo scores (por fallos LLM), skip
        if df_scores.empty:
            print(f"[WARNING] Sin scores válidos en {path.name}")
            continue

        df = pd.concat([df.reset_index(drop=True), df_scores.reset_index(drop=True)], axis=1)
        dfs.append(df)

    if not dfs:
        print(" No se pudo calcular sentimiento general (no hubo scores válidos).")
        return None

    df_total = pd.concat(dfs, ignore_index=True)

    required_cols = ["score_corto", "score_largo", "score_combinado"]
    missing = [col for col in required_cols if col not in df_total.columns]
    if missing:
        print(f"[ERROR] Faltan columnas en df_total general: {missing}")
        return None

    score_corto = df_total["score_corto"].mean()
    score_largo = df_total["score_largo"].mean()
    score_combinado = df_total["score_combinado"].mean()

    out_dir = ensure_date_dir(PROCESSED_BASE, date, hour)
    df_out = pd.DataFrame([{
        "fecha": date.strftime("%Y-%m-%d"),
        "sentimiento_corto": score_corto,
        "sentimiento_largo": score_largo,
        "sentimiento_combinado": score_combinado
    }])
    df_out.to_parquet(out_dir / "sentimiento_general.parquet", index=False)

    print(f" Termómetro emocional guardado en {out_dir / 'sentimiento_general.parquet'}")
    print(f" Corto plazo: {score_corto:.2f}")
    print(f" Largo plazo: {score_largo:.2f}")
    print(f" Combinado: {score_combinado:.2f}")
    return score_combinado


def process_sentiment_by_ticker(ticker, date, hour, sentimiento_general=None):
    dfs = []

    base_dir = RELEVANT_BASE / f"{date.year:04d}" / f"{date.month:02d}" / f"{date.day:02d}"
    if hour:
        base_dir = base_dir / hour

    print(f"[DEBUG] Buscando sentimiento ticker {ticker} en: {base_dir}")

    if not base_dir.exists():
        print(" No existe carpeta de relevantes para el corte.")
        return

    # {TICKER}_*.parquet (ej: AAPL_newsapi.parquet, AAPL_reddit.parquet)
    files = sorted(base_dir.glob(f"{ticker}_*.parquet"))
    if not files:
        print(f"No se encontraron textos relevantes para {ticker}")
        return

    for path in files:
        df = pd.read_parquet(path)
        columna = pick_text_column(df)

        df_scores_series = df[columna].apply(analyze_sentiment)
        df_scores = pd.DataFrame([s for s in df_scores_series.tolist() if s is not None])

        if df_scores.empty:
            print(f"[WARNING] Sin scores válidos en {path.name}")
            continue

        df = pd.concat([df.reset_index(drop=True), df_scores.reset_index(drop=True)], axis=1)
        dfs.append(df)

    if not dfs:
        print(f"No se pudo calcular sentimiento para {ticker} (no hubo scores válidos).")
        return

    df_total = pd.concat(dfs, ignore_index=True)

    required_cols = ["score_corto", "score_largo", "score_combinado"]
    missing = [col for col in required_cols if col not in df_total.columns]
    if missing:
        print(f"[ERROR] Faltan columnas en df_total para {ticker}: {missing}")
        return

    score_corto = df_total["score_corto"].mean()
    score_largo = df_total["score_largo"].mean()
    score_combinado = df_total["score_combinado"].mean()

    out_dir = ensure_date_dir(PROCESSED_BASE, date, hour)
    df_out = pd.DataFrame([{
        "ticker": ticker,
        "sentimiento_corto": score_corto,
        "sentimiento_largo": score_largo,
        "sentimiento_combinado": score_combinado,
        "fecha": date.strftime("%Y-%m-%d")
    }])
    df_out.to_parquet(out_dir / f"{ticker}.parquet", index=False)

    print(f"Sentimiento procesado para {ticker} → {out_dir / f'{ticker}.parquet'}")
    print(f"Textos procesados: {len(df_total)}")
    print(f"Corto plazo: {score_corto:.2f}")
    print(f"Largo plazo: {score_largo:.2f}")
    print(f"Combinado: {score_combinado:.2f}")



def export_sentiment_summary_to_json(date, hour):
    out_dir = ensure_date_dir(PROCESSED_BASE, date, hour)
    summary = {}

    # General
    p_gen = out_dir / "sentimiento_general.parquet"
    if p_gen.exists():
        df_gen = pd.read_parquet(p_gen)
        if not df_gen.empty:
            summary["GENERAL"] = [{
                "short_score": float(df_gen["sentimiento_corto"].iloc[0]),
                "long_score": float(df_gen["sentimiento_largo"].iloc[0]),
                "combined_score": float(df_gen["sentimiento_combinado"].iloc[0]),
                "date": df_gen["fecha"].iloc[0],
            }]

    # Por ticker
    summary["TICKERS"] = {}
    for p in out_dir.glob("*.parquet"):
        name = p.stem
        if name == "sentimiento_general":
            continue
        df_t = pd.read_parquet(p)
        if df_t.empty:
            continue
        summary["TICKERS"][name.upper()] = [{
            "short_score": float(df_t["sentimiento_corto"].iloc[0]),
            "long_score": float(df_t["sentimiento_largo"].iloc[0]),
            "combined_score": float(df_t["sentimiento_combinado"].iloc[0]),
            "date": df_t["fecha"].iloc[0],
        }]

    # Guardar
    out_json = out_dir / "sentiment_summary.json"
    with out_json.open("w", encoding="utf-8") as f:
        import json
        json.dump(summary, f, ensure_ascii=False, indent=2)


#  Ejecución principal
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, help="Fecha en formato YYYY-MM-DD")
    parser.add_argument("--hour", type=str, help="Hora en formato HHMM")
    args = parser.parse_args()

    date = get_execution_date(args.date)
    hour = get_execution_hour(args.hour)

    sentimiento_general = process_general_sentiment(date, hour)

    tickers = ["AAPL", "TSLA", "GOOGL", "MSFT", "META", "NVDA", "AMZN"]
    for ticker in tickers:
        process_sentiment_by_ticker(ticker, date, hour, sentimiento_general)
    
    export_sentiment_summary_to_json(date, hour)
