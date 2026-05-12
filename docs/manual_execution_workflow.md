# Manual Execution Workflow

The manual execution tracker lets you close the loop after running the daily
capital plan: you record what you actually did in your broker, then compare
it against what the bot recommended.

This is still **manual review only**. No broker connection. No live trading.
No execution automation. No API keys. No network calls. The tracker never
writes `execution.plan` or `final_decision.json`.

## File layout

| Location | Purpose | Committed? |
| --- | --- | --- |
| `config/manual_execution/manual_executions.template.json` | Empty template with `TODO` placeholders. | Yes |
| `config/manual_execution/manual_executions.example.json` | Illustrative example log (matched, partial, and extra cases). | Yes |
| `snapshots/manual_execution/*.json` | Your real, private manual execution logs. | **No** (gitignored) |
| `snapshots/outputs/<date>/manual_execution/` | Generated comparison artifacts. | **No** (gitignored) |

## 1. Generate a starter execution log

```bash
python -m src.tools.create_manual_execution_template --date 2026-05-12
```

Writes `snapshots/manual_execution/2026-05-12.json`, stamped with:

- `as_of = 2026-05-12`
- `execution_log_id = manual-executions-2026-05-12`
- every entry's `executed_at` and `plan_id` set to the same date

Use `--out <path>` for an explicit destination, and `--overwrite` if you
really want to replace an existing file (refused by default).

## 2. Fill the log manually

Open the generated file and replace every `TODO` with what you actually did:

- one entry per executed trade (BUY or SELL)
- real `symbol`, `quantity`, `price`, `price_currency`, `fees`, `fees_currency`
- realistic `executed_at`, `broker`, `notes`

`manual_review_only` stays `true` and `live_trading_enabled` stays `false`.
The loader rejects the file otherwise.

## 3. Compare against the daily plan

```bash
python -m src.tools.compare_manual_execution \
  --plan snapshots/outputs/2026-05-12/capital_routing/daily_capital_plan.json \
  --executions snapshots/manual_execution/2026-05-12.json \
  --artifacts-dir snapshots/outputs/2026-05-12 \
  --usdars-rate 1200
```

This produces:

- `snapshots/outputs/2026-05-12/manual_execution/manual_execution_comparison.json`
- `snapshots/outputs/2026-05-12/manual_execution/manual_execution_report.md`

The summary classifies each symbol as one of:

- **MATCHED** - executed within `max(1 USD, 10% of recommended)` of the plan
- **PARTIAL** - some non-zero execution, but outside the tolerance
- **MISSED** - the plan recommended a buy, you did not execute it
- **EXTRA** - you bought a symbol the plan did not recommend

The summary also reports follow rate, total recommended/executed USD, and
estimated fees in USD.

For machine-readable output add `--json`:

```bash
python -m src.tools.compare_manual_execution \
  --plan snapshots/outputs/2026-05-12/capital_routing/daily_capital_plan.json \
  --executions snapshots/manual_execution/2026-05-12.json \
  --artifacts-dir snapshots/outputs/2026-05-12 \
  --usdars-rate 1200 \
  --json
```

## FX conversion

The tracker prefers the explicit `--usdars-rate` argument. When ARS amounts
are recorded without an FX rate the tracker still computes a number, but
treats the ARS amount as USD-equivalent and emits an explicit warning in both
the JSON summary and the Markdown report. Provide the rate for accurate
totals.

## Reminders

- **Manual review only.** No broker integration. No live trading. No orders.
- **Do not commit private execution logs.** `snapshots/manual_execution/*.json`
  is gitignored on purpose; only the `.gitkeep` placeholder is tracked.
- **Forbidden artifacts.** The tracker never writes `execution.plan` or
  `final_decision.json`. If you see those files in your output directory,
  something is wrong - delete them and investigate.
