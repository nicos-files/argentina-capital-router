# Comprehensive Analysis (Main)

## Architecture Summary
This is a Python monorepo that implements:
- An ETL pipeline for prices, fundamentals, and sentiment
- Feature engineering and ML training
- Signal generation with confidence and risk context
- Backtesting and reporting
- A decision layer that produces long-term and intraday recommendations

## Primary Flow (Happy Path)
1. **ETL Orchestration** (`src/orchestrator/data_orchestrator.py`)
   - Runs ingest modules for prices, fundamentals, sentiment
   - Tracks last-run state and new data via file mtimes
   - Writes `data/logs/data_ready.json` and `data/logs/data_orchestrator_state.json`
   - Consolidates daily outputs per module

2. **Processing** (`src/execution/process/*`)
   - `process_prices` cleans raw prices into processed prices
   - `process_indicators` builds technical indicators
   - `process_fundamentals` normalizes fundamentals from Alpha Vantage + Finnhub
   - `relevance_filter` filters raw sentiment via LLM
   - `process_sentiment` scores and aggregates sentiment

3. **Feature Engineering** (`src/pipeline/feature_engineering.py`)
   - Merges indicators + fundamentals + sentiment
   - Adds lagged features and target labels
   - Writes hourly and daily feature sets

4. **Model Training** (`src/pipeline/train_model.py`)
   - Trains XGBoost classifiers and regressors on features
   - Saves models to `models/`

5. **Signal Generation** (`src/pipeline/generate_signals.py`)
   - Loads latest features and trained model
   - Produces score, expected return, volatility, and signal
   - Writes `strategy_signals.csv` and optional equity simulation

6. **Backtesting** (`src/backtest/backtest_strategy.py`)
   - Loads features and model predictions
   - Executes a daily backtest with cost assumptions
   - Writes equity curve and summary metrics

7. **Decision Layer** (`src/agents/orchestrator_agent.py` + `src/run.py`)
   - Builds context from signals, backtest, and sentiment
   - Uses long-term and intraday agents to select positions
   - Writes `data/results/final_decision.json`

## Execution Entrypoints
- `src/run.py` - end-to-end daily run (ETL + modeling + decision)
- `src/orchestrator/data_orchestrator.py` - ETL pipeline
- `src/pipeline/feature_engineering.py` - features
- `src/pipeline/train_model.py` - training
- `src/pipeline/generate_signals.py` - signals
- `src/backtest/backtest_strategy.py` - backtest
- `main.py` - references missing `src/utils/hello.py`

## Configuration Patterns
- `src/backtest/config_backtest.json` for backtest parameters
- `src/autogen/agent_configs.yaml` for agent roles and model params
- `.env` for API keys and model settings (loaded by agents)
- `src/utils/execution_context.py` centralizes date/hour and data path conventions

## LLM and Agent Layer
- `src/agents/agent_definitions.py` wires Sentiment/Strategy/User agents
- `src/agents/strategy_agent.py` calls OpenAI API (requires `OPENAI_API_KEY`)
- `src/agents/orchestrator_agent.py` coordinates ETL + modeling + decisions
- LLM interactions are logged to `data/logs/*.parquet`

## Data and Logging Observations
- Data folders are created at runtime; repo lacks `data/` by default
- Logs and caches are persisted under `data/logs`, `data/cache`, `data/indexes`
- Daily consolidation writes `data/processed_daily/*_daily.parquet`

## Gaps and Inconsistencies (Observed)
- `src/execution/run_pipeline.py` imports `agents.strategy_llm_agent` which does not exist
- `features.fundamental_analysis` is referenced but missing
- `main.py` imports `src/utils/hello.py` which is missing
- Several modules hardcode absolute paths (`C:/Users/...`) via `sys.path.append`
- API keys are embedded in code (`alphaV_fetcher.py`, `ingest_fundamentals.py`, `ingest_sentiment.py`)
- Optional dependency `python-dotenv` is used but not listed in `requirements.txt`

## Configuration and Control Flags
- Orchestrator supports skip/force flags for each ETL step
- Signals and decisions are filtered by threshold, max positions, liquidity and volatility limits
- Backtest risk controls: stop loss, take profit, clip returns
