# Architecture (Main)

## Executive Summary
This is a Python-based quantitative trading pipeline that ingests market, fundamentals, and sentiment data, processes and consolidates it into features, trains ML models, generates trading signals, and runs a backtest. A decision layer (LLM agents) produces long-term and intraday recommendations from the signal set.

## Technology Stack
See `docs/technology-stack.md` for details. Highlights:
- Python + pandas/numpy
- ML: scikit-learn, XGBoost, LightGBM, PyTorch
- Backtesting: backtesting, vectorbt
- Orchestration: Prefect
- Explainability: SHAP, LIME
- Storage: Parquet + DuckDB

## Architecture Pattern
- **Batch ETL pipeline** with staged ingest -> process -> feature -> model -> signals -> backtest -> decisions.
- **File-based data lake** organized by date/hour under `data/` (created at runtime).
- **Agent-driven decisioning** using LLMs for sentiment filtering and final recommendations.

## Data Architecture
See `docs/data-models-main.md`. Key flows:
- Raw ingests (prices, fundamentals, sentiment) -> processed datasets -> daily consolidated datasets
- Feature sets per hour/day -> trained models -> signal outputs -> backtest metrics

## API Design
No API layer detected. The system currently operates via scripts and file outputs.

## Component Overview
Core modules:
- `src/orchestrator/` - ETL orchestration and state tracking
- `src/execution/` - ingest + processing modules
- `src/pipeline/` - feature engineering, model training, signal generation
- `src/backtest/` - backtest pipeline and metrics
- `src/agents/` - long-term and intraday decision agents

## Source Tree
See `docs/source-tree-analysis.md` for annotated structure.

## Development Workflow
See `docs/development-instructions.md` for setup and execution commands.

## Deployment Architecture
No deployment configuration detected. See `docs/deployment-configuration.md`.

## Testing Strategy
Unit tests run via `unittest` (`python -m unittest discover -s tests -p "test_*.py"` or `python scripts/run_tests.py`). CI should invoke the same command.
