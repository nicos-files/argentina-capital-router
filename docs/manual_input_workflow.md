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

### Input quality checks

The validator also runs a set of semantic *quality checks* on top of the
schema validation. They are deliberately permissive by default (warnings
only) and become hard errors under `--strict`. The checks cover:

- **TODO/placeholder markers.** Strings containing `TODO`, `placeholder`,
  `template file`, or `replace` (case-insensitive) anywhere in the JSON.
- **Placeholder numerics.** Market quote prices or FX rates equal to
  `1.0`; rate inputs that are all zero; portfolio positions whose
  quantity and average cost are both exactly `1.0`; cash amounts equal to
  `1.0`.
- **Snapshot date mismatch.** Only when `--expected-date YYYY-MM-DD` is
  passed.
- **Unknown symbols.** Symbols that are not in the configured
  Argentina/CEDEAR universe (`config/data_inputs/ar_long_term_universe.json`).
- **Missing required FX.** Any ARS-denominated quote or position requires
  a `USDARS_MEP` entry in `fx_rates`.
- **Missing position price.** When both snapshots are provided, every
  portfolio position must have a matching market quote.
- **Incomplete snapshot.** `quality.completeness != "complete"`.

In `--strict` mode the following warning codes are promoted to errors and
cause exit code 1: `TODO_MARKER`, `PLACEHOLDER_VALUE`,
`SNAPSHOT_DATE_MISMATCH`, `UNKNOWN_SYMBOL`, `INCOMPLETE_SNAPSHOT`,
`MISSING_REQUIRED_FX`, `MISSING_POSITION_PRICE`.

**Before running the daily plan with real money on the line**, make sure
your snapshots:

- have `quality.completeness` set to `"complete"`,
- have no `TODO`/`placeholder`/`replace` strings left over,
- have real (non-1.0) prices/FX/quantities/costs,
- include `USDARS_MEP` if you hold ARS cash or ARS-priced positions,
- have a matching market quote for every portfolio position,
- and use only symbols from the configured universe.

Example strict invocation:

```bash
python -m src.tools.validate_manual_inputs \
  --market-snapshot snapshots/market/2026-05-12.json \
  --portfolio-snapshot snapshots/portfolio/2026-05-12.json \
  --expected-date 2026-05-12 \
  --strict
```

Add `--json` to either invocation to get a machine-readable summary
instead of human-friendly text. The JSON includes a `quality` block with
`ok`, `strict`, `errors_count`, `warnings_count`, and a list of issues
(each with `severity`, `code`, `message`, `path`, and optionally
`symbol`).

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

## 5. (Optional) Assemble a snapshot from a provider chain

If you want to bootstrap a snapshot from a deterministic example, or fall
back to a hand-edited manual snapshot when other free providers are
unavailable, the codebase ships a small **provider chain** abstraction in
`src/market_data/snapshot_providers.py`.

The chain is strictly no-cost and offline today:

- `StaticExampleSnapshotProvider` - deterministic in-memory fixture used by
  tests and demos. **Not real market data.**
- `ManualFileSnapshotProvider(path)` - wraps an on-disk
  `manual_market_snapshot.json` and serves only the symbols / FX pairs /
  rate keys you ask for.
- `assemble_market_snapshot(request, providers)` - walks providers in order
  (first-hit-wins per item), reports `provider_sources`, fills in
  `missing_symbols` / `missing_fx_pairs` / `missing_rate_keys`, and labels
  the resulting `ManualMarketSnapshot` as `complete` / `partial` /
  `minimal` so the existing **input quality validators** can promote gaps
  to errors under `--strict`.

Example (Python):

```python
from src.market_data.snapshot_providers import (
    MarketSnapshotRequest,
    StaticExampleSnapshotProvider,
    ManualFileSnapshotProvider,
    assemble_market_snapshot,
)

request = MarketSnapshotRequest(
    as_of="2026-05-12",
    symbols=("SPY", "GGAL"),
    fx_pairs=("USDARS_MEP",),
    rate_keys=("money_market_monthly_pct",),
)

assembled = assemble_market_snapshot(
    request,
    [
        StaticExampleSnapshotProvider(),
        ManualFileSnapshotProvider("snapshots/market/2026-05-12.json"),
    ],
)

# assembled.snapshot is a ManualMarketSnapshot suitable for the validators
# and the daily plan. assembled.missing_* and assembled.warnings tell you
# what was not covered and which provider served each item.
```

Free-tier / public providers will plug into the same `MarketSnapshotProvider`
abstraction in a later slice. Hard rules for any future provider:

- API keys MUST come from environment variables or explicit CLI arguments.
- A missing key MUST degrade to an empty `PartialMarketSnapshot` + warning,
  never crash the workflow (unless the caller asks for strict mode).
- API keys MUST NOT be written to artifacts, printed, or embedded in
  exception messages.
- Tests MUST mock the HTTP boundary and MUST NOT hit the network.

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
