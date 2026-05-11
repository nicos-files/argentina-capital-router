import pandas as pd
import argparse
from pathlib import Path
from src.utils.execution_context import (
    get_execution_date,
    get_execution_hour,
    ensure_date_dir
)

# Columnas clave por fuente
alpha_cols = {
    "Symbol": "ticker",
    "PERatio": "pe_ratio",
    "PriceToBookRatio": "pb_ratio",
    "ReturnOnEquityTTM": "roe",
    "ReturnOnAssetsTTM": "roa",
    "DebtToEquity": "de_ratio",
    "DividendYield": "dividend_yield",
    "EPS": "eps",
    "SharesOutstanding": "shares_outstanding",
    "PercentInstitutions": "percent_institutions",
    "PercentInsiders": "percent_insiders"
}

finnhub_cols = {
    "peBasicExclExtraTTM": "pe_ratio",
    "pbAnnual": "pb_ratio",
    "roeTTM": "roe",
    "roaTTM": "roa",
    "totalDebt/totalEquityAnnual": "de_ratio",
    "dividendYieldIndicatedAnnual": "dividend_yield",
    "epsInclExtraItemsAnnual": "eps",
    "grossMarginTTM": "gross_margin",
    "operatingMarginTTM": "operating_margin",
    "netMarginTTM": "net_margin",
    "freeCashFlowAnnual": "free_cash_flow",
    "shareOutstanding": "shares_outstanding",
    "yearToDatePriceReturnDaily": "ytd_return"
}

ROOT = Path(__file__).resolve().parents[3]
RAW_BASE = ROOT / "data" / "raw" / "fundamentals"
PROCESSED_BASE = ROOT / "data" / "processed" / "fundamentals"
FUENTES = ["alphaV", "finnhub"]

def _raw_path(provider: str, ticker: str, date, hour: str) -> Path:
    return RAW_BASE / provider / ticker / f"{date.year:04d}" / f"{date.month:02d}" / f"{date.day:02d}" / hour / f"{ticker}.parquet"


def _load_optional_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception as exc:
        print(f" Error leyendo {path}: {exc}")
        return pd.DataFrame()


def process_fundamentals(ticker: str, date, hour: str):
    alpha_path = _raw_path("alphaV", ticker, date, hour)
    finnhub_path = _raw_path("finnhub", ticker, date, hour)

    df_alpha = _load_optional_parquet(alpha_path)
    df_finnhub = _load_optional_parquet(finnhub_path)
    if df_alpha.empty and df_finnhub.empty:
        print(f" Archivos faltantes para {ticker}")
        return

    print(f" Procesando fundamentales: {ticker}")

    final_data = {v: None for v in alpha_cols.values()}
    final_data.update({v: None for v in finnhub_cols.values()})

    if not df_alpha.empty:
        for raw_col, final_col in alpha_cols.items():
            if raw_col in df_alpha.columns:
                final_data[final_col] = df_alpha.at[0, raw_col]

    if not df_finnhub.empty:
        for raw_col, final_col in finnhub_cols.items():
            if raw_col in df_finnhub.columns:
                final_data[final_col] = df_finnhub.at[0, raw_col]

    df = pd.DataFrame([final_data])
    df["ticker"] = ticker
    df["source_count"] = int((not df_alpha.empty) + (not df_finnhub.empty))
    df = df.convert_dtypes()

    nulls = df.isnull().sum().sum()
    total = df.shape[1] - 2
    completeness = (total - nulls) / total

    umbral_minimo = 0.35 if df["source_count"].iloc[0] == 1 else 0.55
    if completeness >= umbral_minimo:
        out_dir = ensure_date_dir(PROCESSED_BASE, date, hour)
        out_path = out_dir / f"{ticker}.parquet"
        df.to_parquet(out_path, index=False)
        print(f"  {ticker} incluido ({completeness:.0%})  {out_path}")
    else:
        print(f"  {ticker} excluido por baja completitud ({completeness:.0%})")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, help="Fecha en formato YYYY-MM-DD")
    parser.add_argument("--hour", type=str, help="Hora en formato HHMM")
    args = parser.parse_args()

    date = get_execution_date(args.date)
    hour = get_execution_hour(args.hour)

    tickers_alpha = [d.name for d in (RAW_BASE / "alphaV").iterdir() if d.is_dir()] if (RAW_BASE / "alphaV").exists() else []
    tickers_finnhub = [d.name for d in (RAW_BASE / "finnhub").iterdir() if d.is_dir()] if (RAW_BASE / "finnhub").exists() else []
    tickers = sorted(set(tickers_alpha) | set(tickers_finnhub))

    for ticker in tickers:
        process_fundamentals(ticker, date, hour)
