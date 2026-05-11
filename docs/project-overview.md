# Project Overview

**Project:** quant-trading-bot

## Purpose
Modular quantitative trading pipeline that ingests prices, fundamentals, and sentiment, generates features, trains models, produces signals, and creates long-term/intraday recommendations with backtesting outputs.

## Tech Stack Summary
See `docs/technology-stack.md` for full details. Key stack:
- Python, pandas, numpy
- ML: scikit-learn, XGBoost, LightGBM, PyTorch
- Orchestration: Prefect
- Backtesting: backtesting, vectorbt
- Storage: Parquet + DuckDB

## Architecture Type
- Batch ETL pipeline with model training and signal generation
- File-based data lake under `data/` (runtime generated)

## Repository Structure
- Monolith with a single main part
- Core modules live under `src/`

## Key Documentation
- `docs/architecture.md`
- `docs/source-tree-analysis.md`
- `docs/data-models.md`
- `docs/development-guide.md`
