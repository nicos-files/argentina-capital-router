# Development Instructions

## Prerequisites
- Python (version not specified in repo; inferred from `requirements.txt`)
- pip for dependency installation

## Setup
1. Create and activate a virtual environment
2. Install dependencies:
   - `pip install -r requirements.txt`

## Environment Variables
The code expects environment variables for LLM access (loaded via `dotenv`):
- `OPENAI_API_KEY`
- `RELEVANCE_MODEL` (optional)
- `SENTIMENT_MODEL` (optional)
- `STRATEGY_MODEL` (optional)

Note: Some ingest scripts currently hardcode API keys in code (Alpha Vantage, Finnhub, NewsAPI). Consider moving those to `.env`.

## Execution (Common Entrypoints)
- End-to-end run: `python -m src.run`
- ETL only: `python -m src.orchestrator.data_orchestrator`
- Feature engineering: `python -m src.pipeline.feature_engineering`
- Train models: `python -m src.pipeline.train_model`
- Generate signals: `python -m src.pipeline.generate_signals`
- Backtest: `python -m src.backtest.backtest_strategy`

## Testing
- Run unit tests: `python -m unittest discover -s tests -p "test_*.py"` (or `python scripts/run_tests.py`)

## Notes
- `README.md` describes an older file layout; prefer `src/` entrypoints listed above.
- Data outputs are written to `data/` at runtime (not in repo).
