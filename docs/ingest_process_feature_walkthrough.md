# Pipeline Walkthrough (Orchestrator Order)

## 0. Orchestrator overview
- Orchestrator file: `src/orchestrator/data_orchestrator.py`
- Entry commands:
  - `python -m src.orchestrator.data_orchestrator`
  - `python -m src.run` (calls `run_pipeline`, which calls `OrchestratorDecisionAgent.run_day` and `run_etl_pipeline`)
- Orchestrator entrypoints:
  - `orchestrate(...)` in `src/orchestrator/data_orchestrator.py`
  - `run_script(name, module, args)` in `src/orchestrator/data_orchestrator.py`
  - `run_etl_pipeline(...)` in `src/orchestrator/data_orchestrator.py`

Exact step order (from `orchestrate`):
1) `alphaV_fetcher` -> `src.execution.ingest.alphaV_fetcher`
2) `fetch_prices` -> `src.execution.ingest.fetch_prices`
3) `ingest_fundamentals` -> `src.execution.ingest.ingest_fundamentals`
4) `ingest_sentiment` -> `src.execution.ingest.ingest_sentiment`
5) `process_prices` -> `src.execution.process.process_prices`
6) `process_indicators` -> `src.execution.process.process_indicators`
7) `process_fundamentals` -> `src.execution.process.process_fundamentals`
8) `relevance_filter` -> `src.execution.process.relevance_filter`
9) `process_sentiment` -> `src.execution.process.process_sentiment`
10) `daily_consolidator` -> `src.execution.curated.daily_consolidator` (modules: prices, fundamentals, sentiment, indicadores, features)
11) `feature_engineering` -> `src.pipeline.feature_engineering` (called in `OrchestratorDecisionAgent._run_modeling_pipeline`)

Notes:
- Ingest/process steps are executed via `subprocess.run([sys.executable, "-m", module, ...])`.
- Process steps are conditional on new data or `--force-*` flags.

## 1. Ingestion stage (in orchestrator order)

### 1.1 alphaV_fetcher
- Location: `src/execution/ingest/alphaV_fetcher.py`
- Entrypoint: `python -m src.execution.ingest.alphaV_fetcher --date=YYYY-MM-DD --hour=HHMM`
- Inputs:
  - Alpha Vantage API (TIME_SERIES_DAILY)
  - Hardcoded API key in file
  - Existing raw files used for `has_prior_data` (determines outputsize)
- Outputs:
  - `data/raw/prices/alphaV/<TICKER>/YYYY/MM/DD/HHMM/alphaV_<TICKER>.parquet`
- Schema produced:
  - Columns: `open`, `high`, `low`, `close`, `volume`
  - Dtypes: float64 (per sample)
  - Index: DatetimeIndex from API response (no `date` column)
  - Primary key: implicit index (date)
  - Timestamp format: date-only; timezone not set
- Normalizations performed:
  - Rename API columns (`1. open` -> `open`, etc.)
  - Sort by index ascending
  - Cast numeric columns to float
  - Does not add a `ticker` column
- Failure modes / gotchas:
  - Alpha Vantage rate limits / premium-only features (empty response)
  - `outputsize` is forced to "compact" (see `alphaV_fetcher.py:28`)
  - Writes no file if response is empty

### 1.2 fetch_prices
- Location: `src/execution/ingest/fetch_prices.py`
- Entrypoint: `python -m src.execution.ingest.fetch_prices --date=YYYY-MM-DD --hour=HHMM`
- Inputs:
  - Stooq via `pandas_datareader.data.DataReader`
  - Ticker list from `tickers_us` and `tickers_ba`
  - Existing raw files to set `start_date` incrementally
- Outputs:
  - `data/raw/prices/<TICKER>/YYYY/MM/DD/HHMM/prices_<TICKER>.parquet`
- Schema produced:
  - Columns: `date`, `open`, `high`, `low`, `close`, `volume`, `ticker`
  - Dtypes (sample): `date` datetime64[ns], OHLC float64, `volume` int64/float64, `ticker` object
  - Primary key: `(ticker, date)`
  - Timestamp format: `date` column, naive (no timezone)
- Normalizations performed:
  - Reset index; lowercase column names
  - Add `ticker` column
  - Sort by `date`
  - Require all OHLCV columns; otherwise skip
- Failure modes / gotchas:
  - Network errors from Stooq
  - Empty response for ticker
  - Ticker naming includes suffixes `.US` or `.BA`

### 1.3 ingest_fundamentals
- Location: `src/execution/ingest/ingest_fundamentals.py`
- Entrypoint: `python -m src.execution.ingest.ingest_fundamentals --date=YYYY-MM-DD --hour=HHMM`
- Inputs:
  - Alpha Vantage `OVERVIEW` endpoint
  - Finnhub `stock/metric` endpoint (metric=all)
  - Hardcoded API keys in file
- Outputs:
  - `data/raw/fundamentals/alphaV/<TICKER>/YYYY/MM/DD/HHMM/<TICKER>.parquet`
  - `data/raw/fundamentals/finnhub/<TICKER>/YYYY/MM/DD/HHMM/<TICKER>.parquet`
- Schema produced:
  - Alpha Vantage: single-row, wide schema (many string-typed fields)
  - Finnhub: single-row, wide schema (mostly float64 fields)
  - Adds `source` column (`alpha_vantage` or `finnhub`)
  - No explicit timestamp field
- Normalizations performed:
  - No type casting; raw API response stored as-is
  - Hash-based skip: file written only if content changed
- Failure modes / gotchas:
  - API rate limits / empty response
  - Alpha Vantage returns string values for numeric fields
  - Finnhub schema is large and may change

### 1.4 ingest_sentiment
- Location: `src/execution/ingest/ingest_sentiment.py`
- Entrypoint: `python -m src.execution.ingest.ingest_sentiment --date=YYYY-MM-DD --hour=HHMM`
- Inputs:
  - NewsAPI `everything` and `top-headlines`
  - Reddit search JSON
  - Hardcoded API key and user-agent
  - Hash index at `data/indexes/sentiment_hashes_seen.csv`
- Outputs:
  - `data/raw/sentiment/<TICKER>/YYYY/MM/DD/HHMM/sentiment_<TICKER>_<source>.parquet`
  - `source` is `newsapi` or `reddit`
- Schema produced (example):
  - `source`, `title`, `publishedAt`, `hash`, plus optional `description`, `subreddit`
  - `publishedAt` is ISO string for NewsAPI, numeric unix timestamp for Reddit
- Normalizations performed:
  - Compute `hash` from title/source/publishedAt to dedupe
  - Filter out previously seen hashes
  - Writes per-source parquet files
- Failure modes / gotchas:
  - NewsAPI rate limits and HTTP errors
  - Reddit responses may not be JSON (content-type check)
  - Mixed timestamp formats

## 2. Processing stage (raw -> processed)

### 2.1 process_prices
- Location: `src/execution/process/process_prices.py`
- Inputs:
  - Raw prices under `data/raw/prices/<provider>/<ticker>/YYYY/MM/DD/HHMM/*.parquet`
- Outputs:
  - `data/processed/prices/YYYY/MM/DD/HHMM/<TICKER>.parquet`
- Transformations:
  - `set_time_index`: uses `datetime` or `timestamp` or `date` column, with `utc=True` conversion (`process_prices.py:29`)
  - Sort index, drop any rows with NaNs
  - Validate required columns `open`, `high`, `low`, `close`, `volume`
  - Cast to numeric and drop invalid rows
  - Writes only OHLCV columns (no `ticker` column)
- Validation checks:
  - Missing required columns -> skip file
- Gotchas:
  - Assumes provider/ticker directory layout (see issues)
  - Writes per-ticker parquet without explicit ticker column

### 2.2 process_indicators
- Location: `src/execution/process/process_indicators.py`
- Inputs:
  - Processed prices: `data/processed/prices/YYYY/MM/DD/HHMM/<TICKER>.parquet`
- Outputs:
  - `data/processed/indicadores/YYYY/MM/DD/HHMM/<TICKER>.parquet`
- Transformations:
  - Rolling indicators (window=20 unless noted):
    - `SMA_20`, `EMA_20`
    - `daily_return` (pct_change)
    - `volatility` (rolling std of daily_return, window=20)
    - `volume_avg` (rolling mean, window=20)
    - `RSI` (14-day, gain/loss rolling mean)
    - `MACD` (EMA 12 - EMA 26), `MACD_signal` (EMA 9)
    - Bollinger bands: `bollinger_upper`, `bollinger_lower`, `bollinger_width`
  - Drop NaNs after indicator creation
  - Add `ticker` column
- Validation checks:
  - Missing price parquet -> skip ticker
- Leakage protections:
  - None (pure rolling indicators)

### 2.3 process_fundamentals
- Location: `src/execution/process/process_fundamentals.py`
- Inputs:
  - Raw fundamentals from both `alphaV` and `finnhub` for the same ticker
- Outputs:
  - `data/processed/fundamentals/YYYY/MM/DD/HHMM/<TICKER>.parquet`
- Transformations:
  - Column mapping from Alpha Vantage and Finnhub to canonical columns
  - Merge into one-row dataframe, add `ticker`
  - Convert dtypes and compute completeness
  - Only write if completeness >= 0.7
- Key mapped outputs (canonical):
  - `pe_ratio`, `pb_ratio`, `roe`, `roa`, `de_ratio`, `dividend_yield`, `eps`,
    `shares_outstanding`, `percent_institutions`, `percent_insiders`, `gross_margin`,
    `operating_margin`, `net_margin`, `free_cash_flow`, `ytd_return`
- Validation checks:
  - Requires both raw sources present
  - Completeness threshold drops sparse rows

### 2.4 relevance_filter
- Location: `src/execution/process/relevance_filter.py`
- Inputs:
  - Raw sentiment: `data/raw/sentiment/<TICKER>/YYYY/MM/DD/HHMM/*.parquet`
  - LLM via `sentiment_agent` (OpenAI client)
  - Cache/index: `data/cache/relevance_cache.parquet`, `data/indexes/sentiment_index.csv`
- Outputs:
  - `data/processed/sentiment/relevant/YYYY/MM/DD/HHMM/<TICKER>_<source>.parquet`
  - Debug: `data/debug/textos_descartados_llm.parquet`, `data/debug/textos_revisados_por_textblob.parquet`
- Transformations:
  - `clean_text`: strip non-ASCII chars
  - Create `texto` column from `title` or `text`
  - LLM relevance filter (`sentiment_agent.relevance_filter`)
  - Cache hits skip LLM
  - Writes relevant subset only
- Validation checks:
  - None besides empty input skip

### 2.5 process_sentiment
- Location: `src/execution/process/process_sentiment.py`
- Inputs:
  - Relevant sentiment files from `data/processed/sentiment/relevant/...`
  - LLM via `sentiment_agent.process_sentiment`
- Outputs:
  - Per ticker: `data/processed/sentiment/YYYY/MM/DD/HHMM/<TICKER>.parquet`
  - General: `data/processed/sentiment/YYYY/MM/DD/HHMM/sentimiento_general.parquet`
  - Summary: `data/processed/sentiment/YYYY/MM/DD/HHMM/sentiment_summary.json`
- Transformations:
  - For each text: parse 3 numeric scores from LLM response
  - Aggregate mean scores per ticker and for economy
  - Write scores with `fecha`
- Validation checks:
  - If LLM response missing numeric scores, row is dropped

### 2.6 daily_consolidator (processed -> processed_daily)
- Location: `src/execution/curated/daily_consolidator.py`
- Inputs:
  - `data/processed/<module>/YYYY/MM/DD/HHMM/**/*.parquet`
- Outputs:
  - `data/processed_daily/<module>_daily.parquet`
  - `data/processed_daily/consolidation_log.parquet`
- Transformations:
  - Read all parquet files for module
  - Infer `ticker` from filename, strip `.US`/`.BA`
  - Concatenate per ticker, drop duplicates
  - Coerce numeric columns for known list
  - Append to existing daily file if present

## 3. Feature engineering stage

- Entrypoint: `python -m src.pipeline.feature_engineering --date=YYYY-MM-DD --hour=HHMM`
- Inputs (daily consolidated):
  - `data/processed_daily/prices_daily.parquet`
  - `data/processed_daily/indicadores_daily.parquet`
  - `data/processed_daily/fundamentals_daily.parquet`
  - `data/processed_daily/sentiment_daily.parquet`
- Outputs:
  - Hourly: `data/processed/features/YYYY/MM/DD/HHMM/features.parquet`
  - Daily consolidate: `data/processed/features/YYYY/MM/DD/features.parquet`

Feature creation (grouped):
- Price-based:
  - `open`, `high`, `low`, `close`, `volume` (from indicators dataset)
  - `daily_return`
- Technical indicators:
  - `SMA_20`, `EMA_20`, `RSI`, `MACD`, `MACD_signal`
  - `bollinger_upper`, `bollinger_lower`, `bollinger_width`
  - Lag features: `RSI_t-1`, `daily_return_t-1`, `MACD_t-1`
- Fundamentals-based (merged from fundamentals_daily):
  - `pe_ratio`, `pb_ratio`, `roe`, `roa`, `de_ratio`, `dividend_yield`, `eps`,
    `shares_outstanding`, `percent_institutions`, `percent_insiders`,
    `gross_margin`, `operating_margin`, `net_margin`, `free_cash_flow`, `ytd_return`
- Sentiment features:
  - `sentimiento_especifico` (per ticker, fallback to general)
  - `sentimiento_general` (economy)
- Interaction features:
  - `RSI_x_volume`
  - `MACD_x_sentimiento`
- Targets:
  - `target_clasificacion` (daily_return > 0)
  - `target_regresion_t+1` (next-day return)
  - `target_clasificacion_t+1` (target_regresion_t+1 > 0.005)
- Time features:
  - `timestamp_proceso` (from date/hour)
  - `timestamp_ejecucion` (now)

Rolling indicator behavior:
- Window sizes: 20 for SMA/EMA/volatility/volume_avg, 14 for RSI
- NaNs appear at window boundaries and are dropped by `df.dropna` in indicators and by `dropna` on selected columns in feature engineering

## 4. Contract summary

Canonical schemas relied on downstream:
- Raw prices (Stooq path):
  - `date` (datetime64[ns], no TZ), `open`, `high`, `low`, `close`, `volume`, `ticker`
- Raw prices (Alpha Vantage path):
  - Datetime index, `open`, `high`, `low`, `close`, `volume`
- Raw fundamentals (alphaV):
  - Single-row snapshot; mostly string-typed fields from Alpha Vantage `OVERVIEW`
- Raw fundamentals (finnhub):
  - Single-row snapshot; mostly float-typed metrics from Finnhub `metric`
- Processed fundamentals:
  - 16 canonical columns (see mapping in `process_fundamentals.py`)
- Indicators:
  - OHLCV + technical indicators + `ticker`
- Features:
  - Indicators + fundamentals + sentiment + targets + timestamps

Required columns by downstream scripts:
- Training (`src/pipeline/train_model.py`):
  - Expects `target_clasificacion`, `target_regresion_t+1`, and feature columns present in `features.parquet`
- Signals (`src/pipeline/generate_signals.py`):
  - Expects `ticker`, `daily_return`, `target_regresion_t+1`, `bollinger_width`, `volatility`, plus metadata join keys
- Backtest (`src/backtest/backtest_strategy.py`):
  - Expects `data/results/strategy_signals.csv`

## 5. Actionable issues discovered

1) Raw prices directory layout mismatch (Stooq ingest vs process_prices)
- Ingest writes to `data/raw/prices/<TICKER>/YYYY/MM/DD/HHMM/prices_<TICKER>.parquet` (`src/execution/ingest/fetch_prices.py:51-57`)
- Processing expects `data/raw/prices/<provider>/<ticker>/YYYY/MM/DD/HHMM/*.parquet` (`src/execution/process/process_prices.py:38, 100-105`)
- Result: `process_prices` treats `AAPL.US` as provider and year as ticker; raw_dir path is wrong.
- Minimal fix: either change fetch_prices path to include provider (`stooq`) or update process_prices to handle ticker-only layout.

2) Ticker normalization inconsistency (.US/.BA stripping)
- Consolidator strips `.US`/`.BA` from filenames (`src/execution/curated/daily_consolidator.py:64`), while fundamentals tickers are already without suffix.
- This can be OK, but it creates a mismatch if any upstream dataset keeps suffixes for join keys.

3) Alpha Vantage raw prices lack `date` column
- `alphaV_fetcher` writes OHLCV with a DatetimeIndex only (no `date` column).
- `process_prices` converts `date`/`timestamp`/`datetime` columns when present; otherwise keeps index.
- Mixed index/column time handling can lead to timezone ambiguity and downstream joins.

4) Fundamentals require both sources
- `process_fundamentals` skips ticker if alphaV or finnhub missing (`process_fundamentals.py:46-58`).
- In alphaV rate-limit conditions, fundamentals are empty and feature engineering can fail due to missing `fundamentals_daily`.

5) Sentiment pipeline depends on OpenAI at processing stage
- `relevance_filter` and `process_sentiment` import `sentiment_agent` which requires `OPENAI_API_KEY` (`relevance_filter.py:29`, `process_sentiment.py:19`).
- If key is missing or calls fail, sentiment_daily will be empty and feature engineering fails (`feature_engineering.py:45`).

Recommended fixes (minimal blast radius):
- Normalize raw price directory layout to a single provider scheme (e.g., `data/raw/prices/stooq/<ticker>/...`).
- Explicitly write a `date` column for alphaV prices (or always enforce index-to-date conversion in process_prices).
- Add a guard in feature_engineering to skip sentiment/fundamentals if daily inputs are missing (or allow optional modules).
