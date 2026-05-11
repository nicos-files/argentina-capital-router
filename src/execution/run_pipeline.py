import time
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src")))

from execution.ingest.scrape_news import get_all_headlines
from execution.ingest.analyze_sentiment_llm import analyze_sentiment_llm
from execution.ingest.fetch_prices import fetch_price_data_safe, save_to_parquet, all_tickers
from execution.ingest.scrape_news import get_all_headlines
from features.technical_indicators import calculate_indicators
from features.fundamental_analysis import get_fundamentals
from pipeline.feature_engineering import combine_features
from agents.strategy_llm_agent import StrategyAgent
from agents.agent_definitions import sentiment_agent
import pandas as pd 

def map_ticker_from_title(title, ticker_list):
    for ticker in ticker_list:
        clean = ticker.replace(".US", "").replace(".BA", "")
        if clean.lower() in title.lower():
            return ticker
    return None

def save_sentiment_results(results):
    os.makedirs("data/processed/", exist_ok=True)
    df = pd.DataFrame(results)
    df.to_parquet("data/processed/sentimiento.parquet", index=False)
    print("✅ Sentimiento guardado en data/processed/sentimiento.parquet")

def save_strategy(ticker, strategy):
    os.makedirs("data/results/", exist_ok=True)
    df = pd.DataFrame([{"ticker": ticker, **strategy}])
    path = f"data/results/estrategia_{ticker.replace('.', '_')}.parquet"
    df.to_parquet(path, index=False)
    print(f"✅ Estrategia guardada en {path}")

def save_indicators(ticker, indicators):
    os.makedirs("data/processed/", exist_ok=True)
    df = pd.DataFrame([{"ticker": ticker, **indicators}])
    path = "data/processed/indicadores.parquet"

    # Si el archivo ya existe, lo agregamos
    if os.path.exists(path):
        existing = pd.read_parquet(path)
        df = pd.concat([existing, df], ignore_index=True)

    df.to_parquet(path, index=False)
    print(f"✅ Indicadores guardados para {ticker}")    


def run_pipeline():
    start_time = time.time()
    tickers = all_tickers

    # Paso 1: Scraping de titulares
    print("📰 Obteniendo titulares...")
    headlines = get_all_headlines()

    # Paso 2: Análisis de sentimiento con LLM
    print("🧠 Analizando sentimiento...")
    sentiment_results = analyze_sentiment_llm(sentiment_agent, headlines)
    sentiment_df = pd.DataFrame(sentiment_results)

    # Enriquecer titulares con ticker si es posible
    sentiment_df["ticker"] = sentiment_df["titular"].apply(lambda x: map_ticker_from_title(x, all_tickers))
    sentiment_df = sentiment_df.dropna(subset=["ticker"])
    save_sentiment_results(sentiment_df)

    sentiment_summary = sentiment_df["sentimiento"].dropna().tolist()

    sentiment_final = max(set(sentiment_summary), key=sentiment_summary.count)
    print(f"🧠 Sentimiento dominante: {sentiment_final}")

    # Guardar sentimiento general
    pd.DataFrame([{"sentimiento_general": sentiment_final}]).to_parquet(
    "data/processed/sentimiento_general.parquet", index=False
    )
    print("✅ Sentimiento general guardado en data/processed/sentimiento_general.parquet")

    fundamentals_list = []
    for ticker in tickers:
        print(f"\n🚀 Procesando {ticker}...")

        # Paso 3: Ingesta de precios
        df = fetch_price_data_safe(ticker)
        if df is None or df.empty:
            print(f"⚠️ Saltando {ticker} por falta de datos.")
            continue
        save_to_parquet(df, ticker)

        # Paso 4: Indicadores técnicos
        indicators = calculate_indicators(ticker)
        save_indicators(ticker, indicators)
        
        # Paso 5: Simulación de fundamentales y predicción
        fundamentals = get_fundamentals(ticker)
        print(f"📉 Fundamentos reales: ROE={fundamentals['ROE']} | P/E={fundamentals['PE']}")
        fundamentals_list.append(fundamentals)

        prediction_score = 0.75

        # Paso 6: Generar estrategia
        strategy_agent = StrategyAgent()
        strategy = strategy_agent.generate_strategy(sentiment_final, indicators, fundamentals, prediction_score)

        # Paso 7: Mostrar resultado
        print(f"📈 Estrategia para {ticker}:")
        print(f"➡️ Acción: {strategy['acción'].upper()}")
        print(f"🧠 Justificación: {strategy['justificación']}")
        print(f"📊 RSI: {strategy['RSI']} | MACD: {strategy['MACD']} | SMA: {strategy['SMA']}")
        print(f"📈 ROE: {strategy['ROE']} | P/E: {strategy['P/E']}")

        
        save_strategy(ticker, strategy)
        
        
    
    df_fundamentals = pd.DataFrame(fundamentals_list)
    df_fundamentals.to_parquet("data/processed/fundamentales.parquet", index=False)
    print("✅ Fundamentales guardados en data/processed/fundamentales.parquet")

    print("\n🧪 Combinando features...")
    combine_features()
    end_time = time.time()
    duration = end_time - start_time
    print(f"\n⏱️ Tiempo total de ejecución: {duration:.2f} segundos")

if __name__ == "__main__":
    run_pipeline()
