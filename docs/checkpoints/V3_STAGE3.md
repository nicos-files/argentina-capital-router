# V3 Stage 3 Checkpoint - Execution Engine (Paper + Live Stub)

Status: FROZEN (Stage 3.0 additive)

## Frozen / Closed

Status: FROZEN  
Tag: v3-0-paper-execution  
Execution mode: paper  
Broker: IOL (stub)  
Note: Stage 3.1 is required for live execution with real money.

## Scope Summary (Diff vs Stage 2.1)

Stage 3 adds an execution engine that consumes `execution.plan` and produces execution results and post-trade positions. V1 and Stage 2 artifacts remain readable and unchanged.

### New modules

- `src/decision_intel/execution/execution_engine.py`
  - Deterministic execution order (SELL first, BUY second), idempotent by `order_id`.
  - Kill switch + paper gate enforcement.
- `src/decision_intel/brokers/iol_adapter.py`
  - Paper mode fill simulation; live mode stub.
- `src/decision_intel/execution/results_writer.py`
  - Writes `execution.results.v1.0.0.json`.
- `src/decision_intel/positions/positions_reconciler.py`
  - Applies fills to positions and cash, validates reconciliation.

### Updated modules

- `src/cli.py`
  - Adds `--execute`, `--paper` (true/false), `--kill-switch`.
- `src/tools/run_all.py`
  - Executes plan in live mode when `--execute` is set.
  - Updates manifest with execution artifacts.
- `src/decision_intel/exports/artifact_exporter.py`
  - Adds CSV export for `execution.results`.
- `src/decision_intel/positions/positions_store.py`
  - Adds snapshot writer helper for post-execution positions.

## New Artifacts (Stage 3.0)

- `runs/{run_id}/artifacts/execution.results.v1.0.0.json`
  - One entry per attempted order:
    - `order_id`, `broker`, `status`, `filled_qty`, `avg_fill_price`, `fees_actual`
    - `timestamps.sent_at`, `timestamps.filled_at`
    - `error`, `paper_mode`
- `runs/{run_id}/artifacts/positions_snapshot_after.json`
  - Positions after execution, broker- and currency-aware.

## Execution Modes

1) Manual (default)
   - `python -m src.cli run-all --mode live`
   - Generates recommendations + execution plan only.
2) Paper trading
   - `python -m src.cli run-all --mode live --execute --paper`
   - Optional: `--skip-live-ingest` to bypass live ingest/sentiment/price steps.
   - Simulates fills at `price_used`, updates positions cache.
3) Live (guarded)
   - `python -m src.cli run-all --mode live --execute --paper=false`
   - Blocked unless paper gate is satisfied; API calls stubbed.

## Safety Guarantees

- Explicit `--execute` required for any execution.
- Kill switch via env `KILL_SWITCH=1` or `data/controls/kill_switch.json`.
- Live execution blocked until paper gate file exists:
  - `data/controls/paper_passed.flag`
- Errors halt execution by default.

## Backward Compatibility Notes

- No changes to existing artifact schema versions.
- `recommendation.outputs` and `execution.plan` unchanged.
- Execution artifacts are additive and optional.

## Verification (Stage 3.0)

Unit tests:

```bash
python -m unittest discover -s tests -p "test_*.py"
```

Offline smoke:

```bash
python -m src.cli run-all --mode offline --date 2026-01-19 --hour 1519 --emit-recommendations
```

Paper trading smoke:

```bash
python -m src.cli run-all --mode live --execute --paper --date 2026-01-19 --hour 1519
```
