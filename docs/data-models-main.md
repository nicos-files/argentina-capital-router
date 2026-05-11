# Data Models (Main)

## Overview
This project builds a data/feature pipeline that produces signals, backtest outputs, and portfolio decisions. The data schemas are implicit in code and materialize as Parquet/CSV/JSON artifacts at runtime. The `data/` directory is not in the repo and is created during execution.

## Storage Layout (Expected at Runtime)
- `data/raw/` - raw ingests by source and date/hour
- `data/processed/` - cleaned and enriched datasets by module
- `data/processed_daily/` - daily consolidated datasets
- `data/processed/features/` - feature sets per hour and daily
- `data/results/` - signals and decision outputs
- `models/` - trained model artifacts
- `simulations/` - backtest curves and summaries
- `data/logs/` - orchestration and LLM logs
- `data/indexes/` - sentiment index files
- `data/cache/` - relevance filter cache

## Core Datasets and Schemas (Inferred)

### Raw Prices
Path pattern:
- `data/raw/prices/{source}/{ticker}/YYYY/MM/DD/HHMM/{source}_{ticker}.parquet`

Inferred fields:
- `date` (or `timestamp`/index)
- `open`, `high`, `low`, `close`, `volume`
- `ticker`

Sources:
- Stooq (via `fetch_prices.py`)
- Alpha Vantage (via `alphaV_fetcher.py`)

### Processed Prices
Path pattern:
- `data/processed/prices/YYYY/MM/DD/HHMM/{ticker}.parquet`

Fields:
- `open`, `high`, `low`, `close`, `volume`
- time index set from `datetime|timestamp|date`

### Technical Indicators
Path pattern:
- `data/processed/indicadores/YYYY/MM/DD/HHMM/{ticker}.parquet`

Fields (added to processed prices):
- `SMA_20`, `EMA_20`, `RSI`, `MACD`, `MACD_signal`
- `bollinger_upper`, `bollinger_lower`, `bollinger_width`
- `daily_return`, `volatility`, `volume_avg`
- `ticker`

### Fundamentals
Path pattern:
- `data/processed/fundamentals/YYYY/MM/DD/HHMM/{ticker}.parquet`

Fields (union of Alpha Vantage + Finnhub mappings):
- `pe_ratio`, `pb_ratio`, `roe`, `roa`, `de_ratio`, `dividend_yield`, `eps`
- `shares_outstanding`, `percent_institutions`, `percent_insiders`
- `gross_margin`, `operating_margin`, `net_margin`, `free_cash_flow`, `ytd_return`
- `ticker`

### Sentiment (Raw)
Path pattern:
- `data/raw/sentiment/{ticker}/YYYY/MM/DD/HHMM/sentiment_{ticker}_{source}.parquet`

Fields (varies by source):
- `source`, `title`, `description`, `publishedAt`

### Sentiment (Relevant Filter)
Path pattern:
- `data/processed/sentiment/relevant/YYYY/MM/DD/HHMM/{ticker}_{source}.parquet`

Fields:
- raw fields + `texto`, `es_relevante`

### Sentiment (Processed)
Path pattern:
- `data/processed/sentiment/YYYY/MM/DD/HHMM/{ticker}.parquet`
- `data/processed/sentiment/YYYY/MM/DD/HHMM/sentimiento_general.parquet`

Fields:
- `sentimiento_corto`, `sentimiento_largo`, `sentimiento_combinado`, `fecha`
- `ticker` (per-ticker files)

### Daily Consolidates
Path pattern:
- `data/processed_daily/{module}_daily.parquet`

Modules:
- `prices`, `fundamentals`, `sentiment`, `indicadores`, `features`

### Feature Sets
Path pattern:
- `data/processed/features/YYYY/MM/DD/HHMM/features.parquet`
- `data/processed/features/YYYY/MM/DD/features.parquet` (daily consolidated)

Fields (composed):
- indicators + fundamentals + sentiment
- lagged features (`RSI_t-1`, `daily_return_t-1`, `MACD_t-1`)
- derived features (`RSI_x_volume`, `MACD_x_sentimiento`)
- targets (`target_clasificacion`, `target_regresion_t+1`, `target_clasificacion_t+1`)
- timestamps (`timestamp_proceso`, `timestamp_ejecucion`)
- `ticker`

### Signals
Path pattern:
- `data/results/strategy_signals.csv`

Fields:
- `ticker`, `score`, `expected_return_pct`, `signal`
- `investment_type`, `timestamp_proceso`, `volatilidad_pct`
- `sector`, `liquidez`, `sentimiento`

### Backtest Outputs
Path pattern:
- `simulations/equity_curve.csv`
- `simulations/backtest_summary.json`
- `simulations/equity_curve_realistic.png`

## Configuration and Parameters
- `src/backtest/config_backtest.json` defines thresholds, costs, and risk settings.
- `src/autogen/agent_configs.yaml` defines LLM agent roles and parameters.
- `.env` expected for model and API keys (loaded by agents and `src/run.py`).

## Notes
- `data/` is generated at runtime; it is not present in the repo.
- Schemas are derived from code, not a central schema registry.
