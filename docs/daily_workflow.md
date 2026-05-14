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

### Or: build the market snapshot automatically

If you do not want to type every CEDEAR price by hand, you can produce a
deterministic market snapshot via the provider chain. See
[`docs/automated_market_snapshot.md`](automated_market_snapshot.md) for
the full reference. Short version:

```bash
python3 -m src.tools.build_market_snapshot \
  --date 2026-05-12 \
  --provider static-example \
  --usdars-mep 1200 \
  --usdars-ccl 1220 \
  --usdars-official 1000 \
  --money-market-monthly-pct 2.5 \
  --caucion-monthly-pct 2.8 \
  --expected-fx-devaluation-monthly-pct 1.5 \
  --out snapshots/market/2026-05-12.json
```

Supported providers today: `static-example` (offline, deterministic,
**not real market data**) and `yahoo` (free, no-auth, delayed,
best-effort). Review every value before treating the resulting snapshot
as authoritative.

**FX / rate input rules** (see
[`docs/automated_market_snapshot.md`](automated_market_snapshot.md) for
the full table):

- `--usdars-mep`, `--usdars-ccl`, `--usdars-official` must each be
  strictly positive and finite. The CLI rejects `0`, negatives, `nan`
  and `inf` with a usage error.
- `--money-market-monthly-pct`, `--caucion-monthly-pct`,
  `--expected-fx-devaluation-monthly-pct` accept `0` and negative
  values (a calm money market is `0%`; a slightly negative expected
  devaluation is legitimate) but reject `nan` / `inf`.
- CLI-supplied FX and rate values are tagged `provider=cli_override`
  inside the snapshot so the audit trail stays clear.
- Missing FX / rate inputs do not crash the build; they downgrade
  `quality.completeness` to `partial` and are listed under
  `missing_fx_pairs` / `missing_rate_keys` in the summary. Strict
  validation then refuses to proceed.

Recommended pattern for a complete-coverage day:

```bash
python3 -m src.tools.build_market_snapshot \
  --date 2026-05-12 \
  --provider static-example \
  --usdars-mep 1200 \
  --usdars-ccl 1220 \
  --usdars-official 1000 \
  --money-market-monthly-pct 2.5 \
  --caucion-monthly-pct 2.8 \
  --expected-fx-devaluation-monthly-pct 1.5 \
  --out snapshots/market/2026-05-12.json

python3 -m src.tools.validate_manual_inputs \
  --market-snapshot snapshots/market/2026-05-12.json \
  --expected-date 2026-05-12 \
  --strict
```

### Running without current holdings

If you do not yet have a portfolio snapshot (first run, cash-on-the-
sidelines only, etc.), pass `--empty-portfolio` to the orchestrator
instead of `--portfolio-snapshot`. The workflow will generate an empty
portfolio snapshot on disk under
`<artifacts-dir>/snapshots/empty_portfolio.json` and run the rest of the
pipeline against it.

`--empty-portfolio` and `--portfolio-snapshot` are mutually exclusive;
exactly one of them is required.

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

## Optional: Telegram notifications

Telegram is intentionally a **later step** in the routine: build the
market snapshot, run the workflow, review the generated artifacts under
`snapshots/outputs/<date>/`, and only then opt in to a summary on your
phone. The notifier is optional and the daily plan / report do not
depend on it.

The workflow can also send a concise Telegram summary after a successful
run. See [`docs/telegram_notifications.md`](telegram_notifications.md) for
the full setup; the short version:

- Dry-run alongside the workflow (no credentials, no network):

  ```bash
  python3 -m src.tools.run_manual_daily_workflow \
    --date 2026-05-12 \
    --market-snapshot snapshots/market/2026-05-12.json \
    --portfolio-snapshot snapshots/portfolio/2026-05-12.json \
    --artifacts-dir snapshots/outputs/2026-05-12 \
    --telegram-dry-run
  ```

- Real send (after exporting `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`):

  ```bash
  python3 -m src.tools.run_manual_daily_workflow \
    --date 2026-05-12 \
    --market-snapshot snapshots/market/2026-05-12.json \
    --portfolio-snapshot snapshots/portfolio/2026-05-12.json \
    --artifacts-dir snapshots/outputs/2026-05-12 \
    --notify-telegram
  ```

If both flags are passed, dry-run wins. A Telegram failure returns exit
code 1 but the daily artifacts are kept.

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

### Input quality checks

The orchestrator runs the validator from
[`docs/manual_input_workflow.md`](manual_input_workflow.md) under the hood
and threads `--date` through as the expected snapshot as-of date. The
checks are intentionally **permissive by default** (warnings only) so a
freshly generated template still produces a daily plan you can inspect,
but they catch common mistakes you don't want to ship to a real run:

- TODO/placeholder strings (`TODO`, `placeholder`, `template file`,
  `replace`) anywhere in the JSON,
- prices/FX rates equal to `1.0`, all-zero rate inputs, position
  quantity+average_cost both `1.0`, cash equal to `1.0`,
- snapshot date mismatch against `--date`,
- symbols outside the configured Argentina/CEDEAR universe,
- ARS amounts without `USDARS_MEP`,
- portfolio positions without a matching market quote,
- `quality.completeness != "complete"`.

In `--strict-inputs` mode those become hard errors and the workflow
refuses to write any artifact. Before a real run, make sure your
snapshots:

- have `quality.completeness = "complete"` and an empty `quality.warnings`,
- have no leftover TODO/placeholder strings,
- have real (non-1.0) prices/FX/quantities/costs,
- include `USDARS_MEP` if you hold any ARS cash or ARS-priced positions,
- match `--date` in their `as_of` fields,
- have a matching market quote for every portfolio position.

Example commands:

```bash
python -m src.tools.validate_manual_inputs \
  --market-snapshot snapshots/market/2026-05-12.json \
  --portfolio-snapshot snapshots/portfolio/2026-05-12.json \
  --expected-date 2026-05-12 \
  --strict
```

```bash
python -m src.tools.run_manual_daily_workflow \
  --date 2026-05-12 \
  --market-snapshot snapshots/market/2026-05-12.json \
  --portfolio-snapshot snapshots/portfolio/2026-05-12.json \
  --strict-inputs
```

The workflow's JSON summary includes `input_quality_ok`,
`input_quality_errors_count`, and `input_quality_warnings_count` when
quality checks ran.

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
