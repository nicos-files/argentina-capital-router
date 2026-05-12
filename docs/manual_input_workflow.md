# Manual Input Workflow

`argentina-capital-router` is **manual review only**. No live trading. No
broker automation. No API keys. No real orders. No network calls. No crypto
runtime. No scraping. No paid data dependency.

Every market price, FX rate, and portfolio holding the tool sees is something
*you* typed (or copied from a brokerage statement) into a local JSON file.
This document explains how to do that safely and repeatably.

## File layout

| Location | Purpose | Committed? |
| --- | --- | --- |
| `config/data_inputs/manual_market_snapshot.example.json` | Reference example with realistic-looking placeholder values, used by tests and demos. | Yes |
| `config/portfolio/manual_portfolio_snapshot.example.json` | Reference example of a portfolio snapshot. | Yes |
| `config/data_inputs/manual_market_snapshot.template.json` | Empty starter template with `TODO` placeholders for market data. | Yes |
| `config/portfolio/manual_portfolio_snapshot.template.json` | Empty starter template with `TODO` placeholders for holdings. | Yes |
| `snapshots/market/*.json` | Your private, real market snapshots. | **No** (gitignored) |
| `snapshots/portfolio/*.json` | Your private, real portfolio snapshots. | **No** (gitignored) |
| `snapshots/outputs/` | Generated daily plan / report artifacts. | **No** (gitignored) |

The `snapshots/` tree is kept in git only via `.gitkeep` files. Anything
real that you put there stays local.

## 1. Generate a starter template

Use the template generator instead of copy-pasting the example by hand:

```bash
python -m src.tools.create_manual_snapshot_template \
  --kind both \
  --date 2026-05-12
```

This writes:

- `snapshots/market/2026-05-12.json`
- `snapshots/portfolio/2026-05-12.json`

Both files start from the committed template, are stamped with the requested
`as_of` date and a deterministic `snapshot_id` (e.g. `manual-market-2026-05-12`),
and contain `TODO` notes everywhere a placeholder needs to be replaced.

Options:

- `--kind market` or `--kind portfolio` to generate just one side.
- `--out-dir <dir>` to write somewhere other than `snapshots/`.
- `--market-out <path>` / `--portfolio-out <path>` for explicit destinations.
- `--overwrite` if you want to replace an existing file (refused by default).

## 2. Fill the files manually

Open each generated file and replace the placeholder values:

- **Market snapshot:** last known CEDEAR/local equity prices (in ARS), latest
  USD/ARS rates (MEP / CCL / official), and your monthly money-market /
  caucion / FX-devaluation assumptions. Drop assets you don't track; do not
  invent prices you don't have.
- **Portfolio snapshot:** cash balances and held positions with quantity,
  average cost, and bucket assignment. Remove any placeholder entries you
  don't actually hold.

When you have replaced every `TODO`, also update `quality.completeness` to
`"complete"` and clear the `quality.warnings` array if you want the data to
pass `--strict` validation.

## 3. Validate the snapshots

```bash
python -m src.tools.validate_manual_inputs \
  --market-snapshot snapshots/market/2026-05-12.json \
  --portfolio-snapshot snapshots/portfolio/2026-05-12.json
```

The validator loads both files with the same parsers the daily plan tool
uses, then values the portfolio against the market snapshot so you can spot
missing prices or missing FX rates before the plan is built. Default mode
exits 0 if the schemas are valid even when there are warnings.

For a stricter check (useful right before running the daily plan for real):

```bash
python -m src.tools.validate_manual_inputs \
  --market-snapshot snapshots/market/2026-05-12.json \
  --portfolio-snapshot snapshots/portfolio/2026-05-12.json \
  --strict
```

In `--strict` mode the validator fails with exit code 1 if:

- either snapshot's `quality.completeness` is not `"complete"`,
- either snapshot has any `quality.warnings` entries,
- any portfolio position has no price in the market snapshot,
- or any ARS amount cannot be converted to USD (missing `USDARS_MEP`).

Add `--json` to either invocation to get a machine-readable summary instead
of human-friendly text.

## 4. Run the daily capital plan

Once the inputs are valid, generate the daily plan and report:

```bash
python -m src.tools.run_daily_capital_plan \
  --as-of 2026-05-12 \
  --market-snapshot snapshots/market/2026-05-12.json \
  --portfolio-snapshot snapshots/portfolio/2026-05-12.json \
  --artifacts-dir snapshots/outputs/2026-05-12
```

The artifact directory will contain `capital_routing/daily_capital_plan.json`,
`long_term/monthly_contribution_plan.json`, and `reports/daily_report.md`.
None of these are orders. None of them are execution plans. Use them as a
manual checklist when you place trades yourself, on your own broker, on your
own time.

## Reminders

- **Manual review only.** This tool does not place orders. It does not
  connect to a broker. It does not need API keys.
- **No network calls.** The runtime never reaches out to the internet, and
  templates/snapshots are plain local JSON.
- **Do not commit private snapshots.** `snapshots/market/*.json`,
  `snapshots/portfolio/*.json`, and `snapshots/outputs/` are gitignored on
  purpose. If you need to share real data, do it outside this repo.
- **Forbidden artifacts.** This product never writes `execution.plan` or
  `final_decision.json`. If you see those names in your output directory,
  something is wrong - delete them and investigate.
