import pandas as pd
import pandas_ta as ta
import os

def calculate_full_indicators(ticker: str) -> dict:
    """
    Calcula indicadores técnicos, fundamentales y derivados para el último día disponible.
    Args:
        ticker (str): Ticker del activo
    Returns:
        dict: Diccionario con features útiles
    """
    price_path = f"data/raw/prices/{ticker.replace('.', '_')}.parquet"
    fund_path = f"data/raw/fundamentals/{ticker.replace('.', '_')}.parquet"
    sentiment_path = f"data/raw/sentiment/{ticker.replace('.', '_')}.parquet"

    # Validar existencia de archivos
    if not os.path.exists(price_path):
        raise FileNotFoundError(f"No se encontró archivo de precios para {ticker}")
    df = pd.read_parquet(price_path)

    # Validar columnas y cantidad mínima
    required_cols = ["close", "high", "low", "open", "volume"]
    if not all(col in df.columns for col in required_cols):
        raise ValueError(f"Faltan columnas clave en precios para {ticker}")
    if len(df) < 30 or df[required_cols].isnull().any().any():
        raise ValueError(f"Datos insuficientes o incompletos en precios para {ticker}")

    # Indicadores técnicos
    df.ta.rsi(length=14, append=True)
    df.ta.macd(append=True)
    df.ta.sma(length=20, append=True)
    df.ta.ema(length=20, append=True)
    df.ta.bbands(length=20, append=True)
    df["daily_return"] = df["close"].pct_change()
    df["volatility"] = df["daily_return"].rolling(window=20).std()
    df["volume_avg"] = df["volume"].rolling(window=20).mean()

    # Laggeados
    df["RSI_t-1"] = df["RSI_14"].shift(1)
    df["daily_return_t-1"] = df["daily_return"].shift(1)
    df["MACD_t-1"] = df["MACD_12_26_9"].shift(1)

    # Targets
    df["target_regresion_t+1"] = df["daily_return"].shift(-1)
    df["target_clasificacion_t+1"] = (df["daily_return"].shift(-1) > 0).astype(int)

    # Fundamentos
    if os.path.exists(fund_path):
        fund = pd.read_parquet(fund_path).dropna().tail(1)
        for col in ["pe_ratio", "pb_ratio", "roe", "roa", "de_ratio", "dividend_yield", "eps",
                    "shares_outstanding", "percent_institutions", "percent_insiders",
                    "gross_margin", "operating_margin", "net_margin", "free_cash_flow", "ytd_return"]:
            if col in fund.columns:
                df[col] = fund[col].values[0]

    # Sentimiento
    if os.path.exists(sentiment_path):
        sent = pd.read_parquet(sentiment_path).dropna().tail(1)
        df["sentimiento_especifico"] = sent.get("sentimiento_especifico", 0)
        df["sentimiento_general"] = sent.get("sentimiento_general", 0)

    # Combinaciones
    df["RSI_x_volume"] = df["RSI_14"] * df["volume"]
    df["MACD_x_sentimiento"] = df["MACD_12_26_9"] * df.get("sentimiento_general", 0)

    # Última fila válida
    latest = df.dropna().tail(1).to_dict("records")[0]
    return latest
