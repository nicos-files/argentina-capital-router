# quant-trading-bot

End-to-end, filesystem-first quantitative investment recommender pipeline:
ingest data, process/feature engineer, train models, generate signals, run backtests,
and produce decision outputs. This repo now includes a Decision Intel artifact
layer that captures run manifests, exports, reports, and portfolio artifacts under
runs/{run_id}/... as a single coherent system.

This README documents the current repo as one integrated system. Any remaining
gaps or placeholders are called out explicitly.

## What This Project Does

The project executes a daily (or ad-hoc) pipeline that:

1) Ingests and processes raw data
2) Builds features
3) Trains models
4) Generates strategy signals
5) Runs backtests
6) Orchestrates decision agents
7) Writes Decision Intel artifacts, exports, and reports (under runs/{run_id}/...)

## Data Flow Overview

```
ETL (ingest/process)
  -> Feature Engineering
  -> Model Training
  -> Signal Generation
  -> Backtest
  -> Decision Agents
  -> Decision Intel artifacts + exports + reports
```

## On-Disk Layouts

### data/

```
data/
  raw/                    # raw ingested data
  raw/prices/normalized/  # canonical normalized prices per ticker
  processed/              # processed data (per module)
  processed_daily/        # daily processed aggregates
  results/                # signals + final decisions (legacy outputs)
  logs/                   # orchestrator logs
  meta/                   # metadata inputs (tickers, etc.)
```

### models/

```
models/
  xgb_clf_*.pkl           # trained classifiers
  xgb_reg_*.pkl           # trained regressors
  feature_importance_*.png
```

### simulations/

```
simulations/
  equity_curve.csv
  backtest_summary.json
  equity_curve_realistic.png
```

### runs/{run_id}/ (Decision Intel)

```
runs/{run_id}/
  manifests/
    run_manifest.v{CURRENT_SCHEMA_VERSION}.json
  artifacts/
    decision.outputs.v{SCHEMA_VERSION}.json
    evaluation.metrics.v{SCHEMA_VERSION}.json
    exports/
      export.*.*           # Story 6.1 exports
    notebook/
      notebook.*.*         # Story 6.3 notebook exports
    portfolio/
      portfolio.aggregation.v{SCHEMA_VERSION}.json
      portfolio.summary.v{SCHEMA_VERSION}.json
      portfolio.comparison.v{SCHEMA_VERSION}.json
  reports/
    run_report.md
    run_report.html
    portfolio_report.md
    portfolio_report.html
```

## Module Groups and IO

### Orchestration

- src/run.py
  Primary entrypoint for end-to-end execution. It resolves date/hour, runs ETL and
  modeling steps (unless skipped), then orchestrates decision agents.
  Outputs: decisions in data/results/, agent exports in data/exports/.

- src/orchestrator/data_orchestrator.py
  ETL pipeline runner, executes ingest/process modules and tracks state/logs.
  Outputs: data/raw/*, data/processed/*, logs under data/logs/.

### Execution (ETL)

- src/execution/ingest/*
  Fetch raw data (prices, fundamentals, sentiment).
  Outputs: data/raw/*.

- src/execution/process/*
  Process raw data into structured daily/feature-ready data.
  Outputs: data/processed/*, data/processed_daily/*.

### Pipeline

- src/pipeline/feature_engineering.py
  Builds features and writes parquet under data/processed/features/...

- src/pipeline/train_model.py
  Trains models and writes under models/.

- src/pipeline/generate_signals.py
  Generates data/results/strategy_signals.csv and optional equity outputs under
  simulations/.

### Backtest

- src/backtest/backtest_strategy.py
  Runs backtests and produces simulations/equity_curve.csv and
  simulations/backtest_summary.json.

### Decision Agents

- src/agents/orchestrator_agent.py
  Reads signals + backtest + sentiment, executes long-term and intraday agents,
  writes decisions under data/results/ and exports under data/exports/.

### Decision Intel (Artifacts, Exports, Reports)

The Decision Intel layer provides deterministic, filesystem-first artifacts under
runs/{run_id}/... It does not recompute or re-run strategy logic; it writes
factual artifacts and reports derived from existing outputs.

Key modules:

- Manifests / Writers
  - src/decision_intel/contracts/manifests/run_manifest_writer.py
  - src/decision_intel/utils/io.py (run directory spine, path validation)

- Core artifacts
  - decision.outputs (from decisions)
  - evaluation.metrics (from backtest summary)

- Exports
  - src/decision_intel/exports/artifact_exporter.py (6.1)
  - src/decision_intel/exports/notebook_exporter.py (6.3)

- Reports
  - src/decision_intel/reports/generator.py (6.2)
  - src/decision_intel/portfolio/report_generator.py (7.4)

- Portfolio
  - src/decision_intel/portfolio/aggregator.py (7.1)
  - src/decision_intel/portfolio/summary.py (7.2)
  - src/decision_intel/portfolio/comparison.py (7.3)

## Decision Intel Artifact System

### Manifest Purpose

Every run has a manifest file under:

```
runs/{run_id}/manifests/run_manifest.v{CURRENT_SCHEMA_VERSION}.json
```

The manifest is the authoritative index for all artifacts produced in that run.
It includes:

- schema_version, reader_min_version, run_id, status
- timestamps (created_at, started_at, completed_at)
- config.snapshot_path
- artifact_index entries

### artifact_index entries

Each artifact entry has:

```
{
  "name": "...",
  "type": "...",
  "path": "relative/path/from/run_root",
  "schema_version": "X.Y.Z",
  "content_hash": "sha256..."
}
```

### Canonical Artifacts

Required (core):
- decision.outputs (JSON payload with decisions=[...] and metadata)
- evaluation.metrics (JSON payload with metrics={...} and metadata)

Optional (may be missing; reports tolerate missing sections):
- evaluation.normalized
- evaluation.comparison
- evaluation.analysis_summary
- evaluation.policy
- evaluation.policy_applied
- evaluation.policy_applied_summary

Portfolio artifacts:
- portfolio.aggregation
- portfolio.summary
- portfolio.comparison

If an optional artifact is missing, report generators include a "not available"
placeholder instead of failing.

## How to Run

### Legacy entrypoints (current)

End-to-end daily run:
```
python -m src.run
```

Run ETL only:
```
python -m src.orchestrator.data_orchestrator
```

Feature engineering:
```
python -m src.pipeline.feature_engineering
```

Train models:
```
python -m src.pipeline.train_model
```

Generate signals:
```
python -m src.pipeline.generate_signals
```

Backtest:
```
python -m src.backtest.backtest_strategy
```

Decision-only run (Decision Intel CLI helper):
```
python -m src.decision_intel.cli.run_decisions --run-id RUN_ID --strategy-config <path> --signals <path>
```

## Configuration

- .env is loaded by src/run.py (OpenAI key, etc.).
  - Example: OPENAI_API_KEY=...

- Backtest config:
  - src/backtest/config_backtest.json

- Portfolio weights (Decision Intel portfolio aggregation):
  - Provide via CLI flags: --weights-json or --weights-file.

## Testing

Run unit tests (canonical runner: `unittest`; pytest is not required):
```
python -m unittest discover -s tests -p "test_*.py"
python scripts/run_tests.py
```

## Notes on Integration State

The Decision Intel layer is implemented and tested, but it is not yet wired
into the end-to-end pipeline. The integration step is intended to:

- Create/update a run manifest during pipeline execution
- Write Decision Intel artifacts under runs/{run_id}/artifacts/...
- Trigger exports and reports

This README documents the integrated workflow and the unified CLI adapter that
bridges the legacy pipeline with Decision Intel artifacts.

## Unified CLI (End-to-End Run + Decision Intel Artifacts)

The unified CLI runs the full pipeline and then generates Decision Intel artifacts
and reports under runs/{run_id}/....

Examples:
```
python -m src.cli run
python -m src.cli run --weights-json '{"AAPL":0.6,"MSFT":0.4}'
python -m src.cli run --weights-file weights.json
python -m src.cli run --run-id 20260112-0930
```

What it does:
1) Runs the legacy pipeline end-to-end (ETL -> features -> train -> signals -> backtest -> agents).
2) Creates/updates a run manifest.
3) Writes Decision Intel artifacts under runs/{run_id}/artifacts/...
4) Generates Decision Intel exports and reports under runs/{run_id}/...

Outputs:
- Legacy outputs:
  - data/, models/, simulations/
- Decision Intel outputs:
  - runs/{run_id}/manifests/run_manifest.v{CURRENT_SCHEMA_VERSION}.json
  - runs/{run_id}/artifacts/...
  - runs/{run_id}/reports/...

Common failures:
- Missing API keys (e.g., OpenAI) required by decision agents.
- Missing backtest outputs (simulations/backtest_summary.json).
- Mapping errors if final_decision.json is missing expected keys (long_term/intraday).

## CLI Usage

Pipeline only:
```
python -m src.cli pipeline --date YYYY-MM-DD --hour HHMM
```

Decision Intel only:
```
python -m src.cli decision-intel --run-id 20260112-0930 --final-decision-path data/results/final_decision.json --backtest-summary-path simulations/backtest_summary.json
```

End-to-end:
```
python -m src.cli run --date YYYY-MM-DD --hour HHMM --weights-json '{"AAPL":0.6,"MSFT":0.4}'
```

Outputs:
- Pipeline outputs under data/ and simulations/
- Decision Intel outputs under runs/{run_id}/manifests/, runs/{run_id}/artifacts/, and runs/{run_id}/reports/

## Historical Features Rebuild

Rebuild daily features for a historical range from normalized prices (no external APIs):

```
python -m src.tools.rebuild_features_history --end-date 2026-01-16 --lookback-days 252 --hour 1513 --mode train
python -m src.tools.rebuild_features_history --start-date 2026-01-01 --end-date 2026-01-16 --mode inference --force
```

Validation checks:
```
find data/processed/features -maxdepth 3 -name "features.parquet" | wc -l
python - <<'PY'
import pandas as pd
df = pd.read_parquet("data/processed/features/2026/01/16/features.parquet")
print(df.shape)
print(df["ticker"].nunique(), df["ticker"].head())
print(df.groupby("ticker").size().max())
PY
python -m src.backtest.backtest_strategy --date 2026-01-16 --lookback-days 252
wc -l simulations/equity_curve.csv
```

## Free-Only Mode

For a low-cost stabilization phase, run the repo with free sources only and a small supported universe.

Current practical constraints:
- US equities / ETFs: `yfinance` first, fallback to Alpha Vantage free.
- Forex: `yfinance` first, fallback to Alpha Vantage free.
- Fundamentals: Alpha Vantage + Finnhub free, US equities only.
- BYMA / CEDEARs: kept in the catalog, but not considered stable in free mode.

Suggested free profiles:
- `free-us-small`: 8 large-cap US equities
- `free-portfolio`: 9 liquid US names / ETFs
- `free-forex`: 4 FX pairs
- `free-core`: US small + FX

Examples:
```
python -m src.execution.ingest.fetch_prices --date 2026-04-22 --hour 1800 --profile free-core --free-only
python -m src.execution.ingest.ingest_fundamentals --date 2026-04-22 --hour 1800 --profile free-portfolio --free-only
```

Recommended free stabilization workflow:
```
python -m src.execution.ingest.fetch_prices --date 2026-04-22 --hour 1800 --profile free-core --free-only
python -m src.execution.process.normalize_prices --date 2026-04-22 --hour 1800
python -m src.execution.ingest.ingest_fundamentals --date 2026-04-22 --hour 1800 --profile free-portfolio --free-only
python -m src.execution.process.process_fundamentals --date 2026-04-22 --hour 1800
python -m src.tools.rebuild_features_history --start-date 2024-01-01 --end-date 2026-04-22 --lookback-days 252 --indicators-lookback-days 400 --hour 1800 --mode train --force
python -m src.pipeline.train_model --date 2026-04-22
python -m src.backtest.backtest_strategy --date 2026-04-22 --lookback-days 252
python -m src.cli run-all --mode offline --date 2026-04-22 --hour 1800 --emit-recommendations
```

Daily paper workflow with the consolidated wrappers:
```
python -m src.cli run-free --date 2026-04-22 --hour 1820 --price-profile free-core --fundamentals-profile free-portfolio --execute --paper true
python -m src.cli close-paper-day --run-id 20260422-1820 --mark-date 2026-04-22
```

Manual execution via Telegram:
- Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`
- Send the recommendation summary after a run:
```
python -m src.cli notify-telegram --run-id 20260422-1820
```
- Or send it directly at the end of the free run:
```
python -m src.cli run-free --date 2026-04-22 --hour 1820 --price-profile free-core --fundamentals-profile free-portfolio --execute --paper true --notify-telegram
```

Current trading mode guidance:
- `Stage 1`: US equities / ETFs and, later, CEDEARs once the source is stable.
- `Stage 1 execution`: paper first, then manual execution from Telegram or execution plan.
- `Stage 2`: broker integration and/or a second broker for forex if the strategy shows real edge.
