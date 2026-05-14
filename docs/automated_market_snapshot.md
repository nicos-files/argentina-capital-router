# Automated Market Snapshot

`src/tools/build_market_snapshot.py` is a small CLI that builds a
`ManualMarketSnapshot`-compatible JSON file from the **existing**
provider-chain abstraction in `src/market_data/snapshot_providers.py`.

This tool exists so that users do not have to type every CEDEAR price by
hand into a manual snapshot. It is intentionally **offline and no-cost**.

## What it is

- A wrapper around `assemble_market_snapshot(request, providers)` that:
  - loads the configured Argentina/CEDEAR universe,
  - asks each provider in the chain for quotes / FX rates / rate inputs,
  - layers user-supplied CLI overrides on top (`--usdars-mep`,
    `--money-market-monthly-pct`, etc.),
  - writes a deterministic JSON file that the existing
    `load_manual_market_snapshot` loader accepts unchanged.
- A safety check after writing: the tool re-loads the output file to make
  sure it round-trips before exiting with success.

## Available providers

| Provider          | Real data? | Auth? | Network? | Coverage      |
| ----------------- | ---------- | ----- | -------- | ------------- |
| `static-example`  | **No** (deterministic fixture) | No | No  | Full universe |
| `yahoo`           | Yes (delayed, read-only)       | No | Yes | Best-effort   |

### `static-example`

Deterministic in-memory fixture. Use it for demos, smoke tests, and any
flow that must run without internet access. The numbers are illustrative
round figures and **are not real market data**.

### `yahoo` (free, no-auth, read-only, delayed)

Calls Yahoo Finance's public `v7/finance/quote` endpoint. Properties:

- **Read-only**, **delayed**, **best-effort**.
- **No API key**, **no payment**, **no login**.
- Network: hits a single HTTPS endpoint via stdlib `urllib`.
- Coverage for Argentina equities and CEDEARs may be incomplete; missing
  symbols are skipped (warning + partial snapshot), never substituted
  with invented prices.
- Symbol resolution uses the universe's
  `source_symbol_map["yfinance"]` field (e.g. `GGAL.BA`). Assets without
  a `yfinance` entry are reported as `unmapped` in the warnings.
- Currently serves quotes only; FX rates and rate inputs in this slice
  must come from `--usdars-*` / `--*-pct` CLI flags or a manually
  edited fallback snapshot.
- HTTP, JSON, and per-symbol failures degrade gracefully: the provider
  returns an empty `PartialMarketSnapshot` plus a warning, never raises.

## What it is **not** in this slice

- **Not a broker connector.** There is no order placement, no execution,
  no balance fetching, no holdings sync. The output describes prices and
  rates only.
- **Not for intraday trading.** Yahoo data is delayed and the workflow
  has no intraday assumptions anywhere.
- **Not authoritative.** Always review every value before treating an
  auto-built snapshot as the basis for a real trade.

## Free / no-cost data policy

Any future provider plugged into the chain must comply with the
repository-wide policy:

- Allowed: static fixtures, free public/no-auth endpoints, free-tier APIs
  with **environment-variable-only** keys (no payment method required).
- Not allowed: paid plans, broker-authenticated APIs, login-based
  scraping, IOL authenticated endpoints, paid BYMA feeds, anything whose
  terms are ambiguous.
- API keys MUST come from `os.environ` or CLI arguments; they MUST never
  be hardcoded, logged, embedded in exception messages, or written into
  artifacts.
- Missing keys MUST degrade to an empty `PartialMarketSnapshot` plus a
  warning, never crash the workflow (unless `--strict` is set elsewhere).
- Tests MUST mock the HTTP boundary and MUST NOT hit the network.

## CLI

### Static example (offline, deterministic)

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

### Yahoo (free, no-auth, best-effort)

```bash
python3 -m src.tools.build_market_snapshot \
  --date 2026-05-12 \
  --provider yahoo \
  --usdars-mep 1200 \
  --usdars-ccl 1220 \
  --usdars-official 1000 \
  --money-market-monthly-pct 2.5 \
  --caucion-monthly-pct 2.8 \
  --expected-fx-devaluation-monthly-pct 1.5 \
  --out snapshots/market/2026-05-12.json
```

If Yahoo coverage is incomplete (it usually will be for the AR /
CEDEAR universe), you have three options:

- **Accept the partial snapshot.** The downstream workflow still runs;
  missing symbols simply do not get allocations. Use `--strict-inputs`
  on `run_manual_daily_workflow` if you want partial snapshots to fail
  loudly instead.
- **Fall back to `static-example`** for demos and smoke tests where
  having values for every symbol matters more than realism.
- **Hand-edit the output file** to fill in or correct prices before
  running the workflow. The file is plain JSON.

Useful flags:

- `--date YYYY-MM-DD` (required) - the `as_of` date stamped into every
  quote / FX rate / rate input written to the file.
- `--out PATH` - output file path. Defaults to
  `snapshots/market/<date>.json` under the repo root.
- `--overwrite` - replace an existing file at `--out`. The default is to
  refuse to clobber so you do not lose a hand-edited snapshot.
- `--universe PATH` - alternate universe file
  (default: `config/market_universe/ar_long_term.json`).
- `--include-disabled` - include disabled / non-long-term assets in the
  request. By default only enabled long-term assets are requested.
- `--provider {static-example,yahoo}` - which provider to use. See the
  table above. `static-example` is fully offline; `yahoo` is best-effort
  and may produce a partial snapshot.
- `--usdars-mep`, `--usdars-ccl`, `--usdars-official` - override FX rates.
  When supplied they win over whatever the chain returned and are
  tagged `provider=cli_override` inside the snapshot.
- `--money-market-monthly-pct`, `--caucion-monthly-pct`,
  `--expected-fx-devaluation-monthly-pct` - override rate inputs.
- `--json` - emit a machine-readable summary on stdout.

## Output

The written file is a regular manual market snapshot. It has the same
schema the rest of the product already understands:

- `manual_review_only=true`, `live_trading_enabled=false`.
- `quotes` keyed by symbol.
- `fx_rates`, `rates` keyed by pair / key.
- `quality.warnings` includes any chain warnings and a note that
  overridden FX/rate values came from CLI flags.
- `quality.completeness` is `complete` only when every requested item
  was served (by either the chain or a CLI override). Otherwise the
  field is `partial` or `minimal`, exactly as the input-quality
  validators expect.

You can edit the file by hand afterwards. The validator, planner, and
daily workflow treat a tool-generated snapshot identically to a manual
one.

## Missing symbols

If the chain cannot find a quote for one of the universe symbols, the
tool:

- omits that symbol from `quotes`,
- includes the symbol in `summary["missing_symbols"]`,
- adds a warning to `quality.warnings`,
- and downgrades `quality.completeness` to `partial` (or `minimal` if
  nothing was served).

Under non-strict mode the rest of the workflow keeps running; under
`validate_manual_inputs --strict` or
`run_manual_daily_workflow --strict-inputs` the gap becomes an error,
as designed.

## End-to-end example

```bash
# 1. Build a market snapshot (offline, deterministic).
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

# 2. Run the daily workflow with no current holdings.
python3 -m src.tools.run_manual_daily_workflow \
  --date 2026-05-12 \
  --market-snapshot snapshots/market/2026-05-12.json \
  --empty-portfolio \
  --artifacts-dir snapshots/outputs/2026-05-12
```

The `--empty-portfolio` flag generates an empty
`ManualPortfolioSnapshot` on disk under
`<artifacts-dir>/snapshots/empty_portfolio.json` and threads that
through the validator and planner. It is mutually exclusive with
`--portfolio-snapshot`.

## Reminders

- **Manual review only.** This tool does not place orders. It does not
  connect to a broker. It does not need API keys.
- **No real market data.** The `static-example` provider is for demos
  and tests. Review every number before you use the resulting snapshot
  for anything that matters.
- **No paid subscriptions.** Any future provider added to the chain must
  satisfy the free-data policy above before merging.
- **No `execution.plan`. No `final_decision.json`.** Those names are
  reserved as forbidden artifacts; the tool never writes them.
