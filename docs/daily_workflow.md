# Daily Workflow

The manual daily workflow orchestrator wires the existing manual tools into
a single command so the end-of-day routine is one invocation instead of
four. It is still **manual review only**. No broker connection. No live
trading. No execution automation. No API keys. No network calls. The
workflow never writes `execution.plan` or `final_decision.json`.

## Prerequisite snapshots

Place your local, private inputs under `snapshots/`:

| File | Required | Purpose |
| --- | :---: | --- |
| `snapshots/market/YYYY-MM-DD.json` | yes | Manual market snapshot (CEDEAR/local equity prices in ARS, USDARS rates, monthly assumptions). |
| `snapshots/portfolio/YYYY-MM-DD.json` | yes | Manual portfolio snapshot (cash + held positions). |
| `snapshots/manual_execution/YYYY-MM-DD.json` | optional | Manual execution log if you want a follow-rate comparison. |

These files are gitignored on purpose. Only the `.gitkeep` placeholders are
tracked.

## Generate the input templates

```bash
python3 -m src.tools.create_manual_snapshot_template \
  --kind both \
  --date 2026-05-12

# optional: execution log template
python3 -m src.tools.create_manual_execution_template \
  --date 2026-05-12
```

Open the generated files and replace every `TODO` with real values before
running the workflow.

## Validate inputs only (read-only)

```bash
python3 -m src.tools.validate_manual_inputs \
  --market-snapshot snapshots/market/2026-05-12.json \
  --portfolio-snapshot snapshots/portfolio/2026-05-12.json
```

The orchestrator runs the same validation internally; use this command
alone when you only want to check inputs without producing artifacts.

## Run the workflow (plan only)

```bash
python3 -m src.tools.run_manual_daily_workflow \
  --date 2026-05-12 \
  --market-snapshot snapshots/market/2026-05-12.json \
  --portfolio-snapshot snapshots/portfolio/2026-05-12.json \
  --artifacts-dir snapshots/outputs/2026-05-12
```

Steps performed:

1. Validate the market and portfolio snapshots.
2. Build the daily capital plan, contribution plan, and Markdown report.
3. Print a concise summary.

Generated artifacts:

- `snapshots/outputs/2026-05-12/capital_routing/daily_capital_plan.json`
- `snapshots/outputs/2026-05-12/long_term/monthly_contribution_plan.json`
- `snapshots/outputs/2026-05-12/reports/daily_report.md`

## Run the workflow with execution comparison

```bash
python3 -m src.tools.run_manual_daily_workflow \
  --date 2026-05-12 \
  --market-snapshot snapshots/market/2026-05-12.json \
  --portfolio-snapshot snapshots/portfolio/2026-05-12.json \
  --executions snapshots/manual_execution/2026-05-12.json \
  --usdars-rate 1200 \
  --artifacts-dir snapshots/outputs/2026-05-12
```

When `--executions` is provided the workflow also produces:

- `snapshots/outputs/2026-05-12/manual_execution/manual_execution_comparison.json`
- `snapshots/outputs/2026-05-12/manual_execution/manual_execution_report.md`

The summary then includes follow rate and matched/partial/missed/extra counts.

## Useful flags

- **`--date YYYY-MM-DD`** sets the as-of date. Defaults to today. Also used
  to derive the default artifacts directory.
- **`--artifacts-dir PATH`** overrides the default
  `snapshots/outputs/<date>/`.
- **`--usdars-rate FLOAT`** is forwarded to the execution comparison to
  convert ARS notional and fees to USD. Without it, ARS amounts are treated
  as USD-equivalent and an explicit warning is emitted.
- **`--carry-from-snapshot`** asks the daily plan builder to derive carry
  inputs from the market snapshot's `rates` block instead of skipping the
  tactical leg.
- **`--strict-inputs`** fails the workflow (exit 1) if validation reports
  partial completeness, quality warnings, missing position prices, or
  missing FX. Useful right before you place real trades.
- **`--json`** prints a machine-readable summary instead of the human
  report.

## Exit codes

| Code | Meaning |
| ---: | --- |
| 0 | Success. |
| 1 | Validation failed, plan failed, or comparison failed. |
| 2 | CLI usage error (e.g. missing required argument). |

## Reminders

- **Manual review only.** This tool does not place orders. It does not
  connect to a broker. It does not need API keys.
- **No network calls.** All inputs are local JSON files.
- **Do not commit private snapshots.** `snapshots/market/*.json`,
  `snapshots/portfolio/*.json`, `snapshots/manual_execution/*.json`, and
  `snapshots/outputs/` are gitignored on purpose.
- **Forbidden artifacts.** The workflow never writes `execution.plan` or
  `final_decision.json`. If you see those files in your output directory,
  something is wrong - delete them and investigate.
