# V1 Checkpoint: Stage 1 (Frozen)

Status: frozen

## Summary

This checkpoint captures the current end-to-end quant-trading-bot pipeline plus Decision Intel artifacts as a reproducible baseline. It documents the single-command entrypoint, time semantics, artifacts, and recommendation policy behavior. Use this document to re-run and verify outputs for regression testing.

## System Overview

End-to-end flow:

1. Orchestrator (ingest + process + consolidate) -> `data/processed_daily/*_daily.parquet`
2. Canonical daily features -> `data/processed/features/YYYY/MM/DD/features.parquet`
3. Backtest -> `simulations/backtest_summary.json`
4. Simulation -> `simulations/resultados.csv` + `simulations/simulate_summary.json`
5. Deterministic final decision -> `data/results/final_decision.json`
6. Decision Intel adapter -> `runs/{run_id}/...` artifacts, exports, and reports
7. Recommendation policy -> `recommendation.outputs.v1.0.0.json` + CSV export

## Single Command Entrypoint (run-all)

Primary entrypoint:

```bash
python -m src.cli run-all --date YYYY-MM-DD --hour HHMM --mode offline --timeout-sec 900 --emit-recommendations
```

### Offline (happy path)

```bash
python -m src.cli run-all --mode offline --date 2026-01-19 --hour 1519 --timeout-sec 900 --emit-recommendations
```

### Live (dry-run and real run)

Dry-run (prints commands only):

```bash
python -m src.cli run-all --mode live --date 2026-01-19 --hour 1519 --dry-run
```

Real run (live ingestion):

```bash
python -m src.cli run-all --mode live --date 2026-01-19 --hour 1519 --timeout-sec 900 --emit-recommendations
```

### Flags and defaults

From `src/cli.py`:

- `--date` (required, `YYYY-MM-DD`)
- `--hour` (required, `HHMM`)
- `--mode` (default `offline`, choices `live|offline`)
- `--timeout-sec` (default `600`)
- `--emit-recommendations` (boolean flag; enabled by default in current CLI)
- `--skip-train` (no-op placeholder)
- `--skip-backtest`
- `--skip-simulate`
- `--dry-run`

## Data/Time Semantics

- `execution_date` / `execution_hour`: the CLI arguments passed to `run-all`.
- `asof_date`: latest canonical features day **<= execution_date**, discovered under:
  - `data/processed/features/YYYY/MM/DD/features.parquet`
- `asof_date` is used as the effective end date for backtest/simulate and written into artifacts.
- It can differ from `execution_date` when features are missing for the requested day.

As-of selection logic is defined in `src/tools/run_all.py::_select_asof_date`.

## Artifacts and Outputs

### Core outputs

- `data/results/final_decision.json`
  - Deterministic top-K decision output.
  - Required fields:
    - `decision.intraday[]` / `decision.long_term[]` with `ticker`, `peso_pct`, `justificacion`, `model_score`
    - `asof_date`, `execution_date`, `execution_hour`, `features_path_used`
- `simulations/backtest_summary.json`
  - Backtest summary metrics, used as `evaluation.metrics`.
- `simulations/simulate_summary.json`
  - Only present if `simulate` ran (skip if `--skip-simulate`).

### Decision Intel run folder

Run folder structure:

```
runs/{run_id}/
  manifests/run_manifest.v1.0.0.json
  artifacts/
    decision.outputs.v1.0.0.json
    evaluation.metrics.v1.0.0.json
    recommendation.outputs.v1.0.0.json
    exports/
      decision.outputs.parquet (or .csv fallback)
      evaluation.metrics.csv
      recommendation.outputs.csv
    reports/
      run_report.md
      run_report.html
```

Manifest version:

- `schema_version`: `1.0.0`
- `reader_min_version`: `1.0.0`

Path normalization:

- All `artifact_index[].path` entries are stored with POSIX separators (forward slashes).

### Canonical Decision Intel artifacts

- `decision.outputs.v1.0.0.json` (authoritative decision artifact)
- `evaluation.metrics.v1.0.0.json` (authoritative evaluation metrics)
- `recommendation.outputs.v1.0.0.json` (recommendation policy output)

## Recommendation Policy: policy.topk.net_after_fees.v1

Policy file: `src/decision_intel/policies/topk_net_after_fees.py`

### Summary

Deterministic, non-learning policy that maps `decision.outputs` into BUY/HOLD/SELL/EXIT recommendations with broker fees and net expected return filters.

### Horizons

- `INTRADAY`
- `LONG_TERM`
- If no long-term decisions exist, the policy falls back to intraday decisions for long-term (annotated in `justificacion`).

### Capital and allocation

- Capital:
  - `INTRADAY`: 100 USD
  - `LONG_TERM`: 500 USD
- Top-K:
  - `INTRADAY`: 5
  - `LONG_TERM`: 8
- Caps (max weight per ticker):
  - `INTRADAY`: 0.25
  - `LONG_TERM`: 0.20
- Minimum net thresholds:
  - `INTRADAY`: 0.008 (0.8%)
  - `LONG_TERM`: 0.05 (5%)
- Minimum order size:
  - `INTRADAY`: 50 USD
  - `LONG_TERM`: 50 USD

Allocation order:

1. Score or peso-based weights -> normalize
2. Apply cap -> normalize
3. Apply min order USD (drop/bump) -> normalize
4. Net-after-fees threshold filtering
5. Re-normalize BUYs per horizon (if any remain)

### Brokers and fees

Hardcoded brokers:

| Broker | commission_pct | min_usd |
| --- | --- | --- |
| balanz | 0.006 | 5 |
| iol | 0.005 | 5 |
| generic_us | 0.002 | 1 |

Round-trip fee: `2 * max(min_usd, commission_pct * usd_target_effective)`

### Positions snapshot

- File: `data/results/positions.json`
- If missing, an example is created.
- Per-asset fields: `asset_id`, `broker`, `qty`, `avg_price`, `currency`.

Action rules (per horizon):

- `BUY`: target_qty > current_qty and net_pct >= threshold
- `HOLD`: target_qty == current_qty > 0, or SELL net < 0
- `SELL`: target_qty < current_qty and net sell > 0
- `EXIT`: target_qty == 0 and current_qty == 0

### Expected return mapping

Heuristic mapping from `model_score` to expected return (non-calibrated):

- `INTRADAY`: `max(0, score - 0.5) * 0.20` (clamped to 0.20)
- `LONG_TERM`: `max(0, score - 0.5) * 0.35` (clamped to 0.40)

Net computation:

- `gross_usd = gross_pct * usd_target_effective`
- `net_usd = gross_usd - fees_estimated_usd`
- `net_pct = net_usd / usd_target_effective`

## Known Limitations

- Currency is assumed USD across artifacts and policy.
- Broker selection is static (no per-order optimization).
- Long-term recommendations may fallback to intraday candidates.
- `model_score -> return` mapping is heuristic, not a calibrated forecast.

## Regression Checklist

### Offline smoke command

```bash
python -m src.cli run-all --mode offline --date 2026-01-19 --hour 1519 --timeout-sec 900 --emit-recommendations
```

### Expected terminal summary lines

- `[RUN-ALL] SUCCESS`
- Per-horizon summary:
  - `INTRADAY summary: capital=... buy_count=...`
  - `LONG_TERM summary: capital=... buy_count=...`

### Required files after run

- `data/results/final_decision.json`
- `simulations/backtest_summary.json`
- `simulations/simulate_summary.json` (unless `--skip-simulate`)
- `runs/{run_id}/manifests/run_manifest.v1.0.0.json`
- `runs/{run_id}/artifacts/decision.outputs.v1.0.0.json`
- `runs/{run_id}/artifacts/evaluation.metrics.v1.0.0.json`
- `runs/{run_id}/artifacts/recommendation.outputs.v1.0.0.json`
- `runs/{run_id}/artifacts/exports/recommendation.outputs.csv`

### Quick sanity checks

- `run_manifest` status is `SUCCESS` and has no `error` field.
- `artifact_index[].path` values use forward slashes.
- For each horizon with BUYs:
  - `sum(weight) == 1.0` (within tolerance)
  - `sum(usd_target_effective) == capital`
  - No `weight` exceeds cap.

## Rollback / Freeze Instructions

Suggested tag:

```bash
git tag v1-checkpoint && git push origin v1-checkpoint
```

Sample run_id to keep as reference:

- `20260119-1519`

Branching recommendation:

- Keep `main` frozen for V1.
- Branch for new changes (e.g., `stage-2` or `v1.1-dev`), and merge back after regression passes.
