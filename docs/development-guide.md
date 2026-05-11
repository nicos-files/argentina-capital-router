# Development Guide

## Setup
- Create and activate a virtual environment
- Install dependencies: `pip install -r requirements.txt`

## Environment
- `.env` is loaded by `src/run.py` and agent definitions
- Expected variables: `OPENAI_API_KEY`, `RELEVANCE_MODEL`, `SENTIMENT_MODEL`, `STRATEGY_MODEL`

## Common Commands
- End-to-end: `python -m src.run`
- ETL only: `python -m src.orchestrator.data_orchestrator`
- Feature engineering: `python -m src.pipeline.feature_engineering`
- Training: `python -m src.pipeline.train_model`
- Signals: `python -m src.pipeline.generate_signals`
- Backtest: `python -m src.backtest.backtest_strategy`

## Testing
- Canonical runner: `unittest`
- Run: `python -m unittest discover -s tests -p "test_*.py"` (or `python scripts/run_tests.py`)
