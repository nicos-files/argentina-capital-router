# V2 Stage 2 Checkpoint - Execution-Ready Enhancements

Status: additive, backward-compatible with V1 (Stage 2.1 additions included)

## Frozen / Closed

- Tag: `v2-1-execution-ready`
- Freeze date: 2026-02-08
- All further changes must go to Stage 3+

## Scope Summary (Diff vs V1)

Stage 2 adds broker-aware execution realism, asset metadata, and guardrails without changing schema versions. All V1 artifacts remain readable; new fields are additive.

### New modules

- `src/decision_intel/brokers/broker_selector.py`
  - Deterministic broker selection by lowest one-way fee.
- `src/decision_intel/assets/asset_metadata.py`
  - Currency, lot size, fractional support, price source.
- `src/decision_intel/positions/positions_store.py`
  - Formal positions snapshot loader (supports legacy list + new object schema).
- `src/decision_intel/execution/plan_writer.py`
  - Execution plan artifact writer (order-level, broker-ready).

### Updated modules

- `src/decision_intel/policies/topk_net_after_fees.py`
  - Broker-aware fees per order, asset metadata, expected_return_source.
  - Positions-based action rules (BUY/HOLD/SELL/EXIT).
  - Guardrails: max_positions_per_horizon, max_turnover (LONG_TERM) with cash retention.
  - Explicit constraints markers (e.g., `cap_relaxed_single_buy`, `max_turnover_long_term`).
  - Execution semantics: order_side/type/TIF, min_notional, FX guardrails, cash clipping.
- `src/decision_intel/recommendations/recommendation_writer.py`
  - Uses positions store loader (cash-by-broker schema).
  - Adds cash_summary + cash_policy to recommendation outputs.
- `src/decision_intel/exports/artifact_exporter.py`
  - Recommendation CSV includes execution fields and FX/cash columns.
  - Execution plan CSV export added.
- `src/tools/run_all.py`
  - Enhanced recommendation summary + "BMAD Review - Missing for Full Automation".
  - Prints cash retained per horizon.
- `src/tools/smoke_recommendations.py`
  - Validates broker selection, currency, lot size, FX guardrails, execution plan presence.

### New tests

- `tests/decision_intel/recommendations/test_broker_selector.py`
- `tests/decision_intel/assets/test_asset_metadata.py`
- `tests/decision_intel/positions/test_positions_store.py`
- `tests/decision_intel/recommendations/test_execution_semantics.py`
- `tests/decision_intel/execution/test_plan_writer.py`

### Test runner

- Canonical runner: `unittest` (`python -m unittest discover -s tests -p "test_*.py"`).
- Helper script: `scripts/run_tests.py`.

## Backward Compatibility Notes

- All artifacts keep their existing schema versions (`v1.0.0`).
- `recommendation.outputs` adds fields but does not remove or rename existing ones.
- `execution.plan` is a new optional artifact; existing consumers can ignore it.
- `positions.json` supports legacy list format and new object format.

## New Fields in recommendation.outputs

Added per item:

- `currency` (`USD` | `ARS`)
- `fx_rate_used` (float | null)
- `fx_rate_source` (string)
- `lot_size` (int)
- `allow_fractional` (bool)
- `price_source` (string)
- `expected_return_source` (`proxy_score` | `model_regression` | `calibrated` | `position_pnl`)
- `fees_one_way`
- `fees_round_trip`
- `order_side` (`BUY` | `SELL`)
- `order_type` (`MARKET`)
- `time_in_force` (`DAY`)
- `order_qty`
- `order_notional_usd`
- `order_notional_ccy`
- `min_notional_usd`
- `order_status` (`READY` | `CLIPPED_CASH` | `BLOCKED_FX` | `BLOCKED_CASH` | `BLOCKED_MIN_NOTIONAL` | `BLOCKED_PRICE` | `NO_ORDER`)
- `cash_available_usd`
- `cash_used_usd`

Added to payload:

- `cash_summary` (per-horizon cash_used/cash_retained)
- `cash_policy` (execution cash handling policy)

CSV export (`runs/{run_id}/artifacts/exports/recommendation.outputs.csv`) now includes:

- `currency`, `fx_rate_used`, `fx_rate_source`
- `lot_size`, `allow_fractional`
- `price_source`, `expected_return_source`
- `fees_one_way`, `fees_round_trip`
- `order_side`, `order_type`, `time_in_force`
- `order_qty`, `order_notional_usd`, `order_notional_ccy`, `min_notional_usd`
- `order_status`, `cash_available_usd`, `cash_used_usd`

## New Artifact: execution.plan

- `runs/{run_id}/artifacts/execution.plan.v1.0.0.json`
- CSV export: `runs/{run_id}/artifacts/exports/execution.plan.csv`
- One row per executable order (READY or CLIPPED_CASH) with broker, qty, order type, FX context, and fee fields (`fees_estimated_usd`, `fees_one_way`, `fees_round_trip`).

## Policy Changes (policy.topk.net_after_fees.v1)

### Broker selection

For each BUY/SELL:

- Select broker with lowest one-way fee using:
  - `commission_pct`
  - `min_usd`
- Persist:
  - `broker_selected`
  - `fees_one_way`
  - `fees_round_trip`
- Selection uses the executable order notional after cash/lot sizing.

### Execution semantics

- `order_type = MARKET`, `time_in_force = DAY` for executable orders.
- `min_notional_usd` enforced as `max(policy_min_order, broker_min_notional)`.
- Cash handling: clip to available cash (order_status = `CLIPPED_CASH`) or block (`BLOCKED_CASH`).
- Partial fills are not modeled; orders are clipped or blocked deterministically.
- FX guardrails: non-USD orders require explicit `fx_rate_used` or are blocked (`BLOCKED_FX`).

### Positions schema (formalized)

`data/results/positions.json` supports:

```
{
  "positions": [
    {
      "asset_id":"NVDA",
      "broker":"iol",
      "qty":2.0,
      "avg_price":480.0,
      "currency":"USD",
      "fx_rate_used":1.0,
      "fx_rate_source":"native_usd"
    }
  ],
  "cash": {"USD": 600.0},
  "cash_by_broker": {"iol": {"USD": 600.0}}
}
```

Legacy list-only format remains supported.
`cash_by_broker` is optional; when present it overrides `cash` for broker-specific limits.

### Asset metadata

Heuristics:

- Ticker with no suffix or `.US` -> USD, allow_fractional = true.
- Other suffix -> ARS, allow_fractional = false.
- `price_source = "features.close"`.
- FX rate semantics:
  - USD assets use `fx_rate_used = 1.0`, `fx_rate_source = "native_usd"`.
  - Non-USD assets require explicit `fx_rate_used`; otherwise orders are blocked with `fx_rate_missing`.

### Expected return source

Priority:

1. `expected_return_gross_pct` in outputs -> `calibrated`
2. `target_regresion_t+1` -> `model_regression`
3. Fallback from `model_score` -> `proxy_score`
4. Position close-outs -> `position_pnl`

### Guardrails

- `max_positions_per_horizon`
  - INTRADAY: 5
  - LONG_TERM: 8
- `max_weight_per_ticker` (unchanged)
  - INTRADAY: 0.25
  - LONG_TERM: 0.20
- `max_turnover` (LONG_TERM only): 1.0 (placeholder cap for now)

If a single BUY exceeds cap, the policy flags:

- `constraints += ["cap_relaxed_single_buy"]`

When constraints bind or cash is insufficient, weights are not renormalized; retained cash is persisted via `cash_summary`.

## Migration / Upgrade Notes

- V1 consumers reading recommendation outputs should ignore unknown fields.
- `positions.json` remains optional; if missing, an example file is created.
- Broker selection is deterministic and fee-based (no broker API dependency).

## Verification (Stage 2)

Run offline smoke:

```bash
python -m src.cli run-all --mode offline --date 2026-01-19 --hour 1519 --timeout-sec 900 --emit-recommendations
python -m src.tools.smoke_recommendations 2026-01-19 1519
```

Expected:

- BUYs exist per horizon when signals permit.
- broker_selected is present for BUY/SELL items.
- qty_target respects lot_size (integer when allow_fractional=false).
- execution.plan artifact + CSV export are created.
- cash_summary reports retained cash when constraints bind.

## BMAD Review - Missing for Full Automation

- BLOCKER: real-time market prices + quote validation
- BLOCKER: broker API auth + order placement
- BLOCKER: order state reconciliation (fills/partials/cancel)
- BLOCKER: position/cash reconciliation with broker
- BLOCKER: risk kill-switch and circuit breakers
- NON-BLOCKER: FX rates feed for non-USD execution (blocked without source)
- NON-BLOCKER: slippage/market impact modeling
- FUTURE IMPROVEMENT: portfolio-level optimization and sizing
- FUTURE IMPROVEMENT: calibrated expected-return mapping
