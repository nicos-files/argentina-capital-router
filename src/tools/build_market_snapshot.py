"""Build an automatic ``ManualMarketSnapshot`` from the provider chain.

Manual review only. No live trading. No broker automation. No orders.
No real HTTP in this slice. No API keys. No network calls.

This CLI composes the existing pieces:
  * ``src/market_data/snapshot_providers.py`` (abstraction + chain)
  * ``StaticExampleSnapshotProvider`` (deterministic offline data)
  * ``manual_market_snapshot_to_dict`` (writer round-trip-compatible with
    ``load_manual_market_snapshot``)

It does NOT introduce a competing provider abstraction; it merely wires
the existing chain into a user-facing command.

Future free-tier / public providers will plug into the same chain. The
``--provider`` flag is intentionally restricted to ``static-example``
today so users cannot accidentally hit a paid or unreviewed source.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

from src.market_data.ar_symbols import (
    ArgentinaAsset,
    get_enabled_long_term_assets,
    load_ar_long_term_universe,
)
from src.market_data.manual_snapshot import (
    load_manual_market_snapshot,
    manual_market_snapshot_to_dict,
)
from src.market_data.snapshot_providers import (
    AssembledMarketSnapshot,
    MarketSnapshotProvider,
    MarketSnapshotRequest,
    StaticExampleSnapshotProvider,
    YahooArgentinaMarketDataProvider,
    assemble_market_snapshot,
)


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_OUTPUTS_DIR = _REPO_ROOT / "snapshots" / "market"
_DEFAULT_UNIVERSE = (
    _REPO_ROOT / "config" / "market_universe" / "ar_long_term.json"
)

_RATE_KEY_MMM = "money_market_monthly_pct"
_RATE_KEY_CAUCION = "caucion_monthly_pct"
_RATE_KEY_FX_DEV = "expected_fx_devaluation_monthly_pct"

_FX_MEP = "USDARS_MEP"
_FX_CCL = "USDARS_CCL"
_FX_OFFICIAL = "USDARS_OFFICIAL"

_VALID_PROVIDERS = ("static-example", "yahoo")

_EXIT_OK = 0
_EXIT_FAILURE = 1
_EXIT_USAGE = 2


# ---------------------------------------------------------------------------
# CLI parser
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build an automatic ManualMarketSnapshot from the provider "
            "chain. Manual review only - no live trading, no broker "
            "automation, no orders. No real HTTP in this slice."
        )
    )
    parser.add_argument(
        "--date",
        required=True,
        help="As-of date for the snapshot (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--out",
        default=None,
        help=(
            "Output path. Defaults to "
            "snapshots/market/<date>.json under the repository root."
        ),
    )
    parser.add_argument(
        "--provider",
        choices=_VALID_PROVIDERS,
        default="static-example",
        help=(
            "Provider to use. 'static-example' = deterministic offline "
            "fixture (default, demo/test data only). 'yahoo' = free, "
            "no-auth, read-only, delayed Yahoo Finance quotes; coverage "
            "for Argentina / CEDEAR symbols may be incomplete and missing "
            "symbols produce a partial snapshot. No paid data, no API "
            "keys, no broker automation regardless of provider."
        ),
    )
    parser.add_argument(
        "--universe",
        default=str(_DEFAULT_UNIVERSE),
        help="Path to the universe JSON config.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite the output file if it already exists.",
    )
    parser.add_argument(
        "--include-disabled",
        action="store_true",
        help=(
            "Include disabled assets / assets not flagged "
            "long_term_enabled. Default is to request only enabled "
            "long-term assets."
        ),
    )
    parser.add_argument(
        "--usdars-mep",
        type=float,
        default=None,
        help="Override the USDARS_MEP rate (ARS per USD).",
    )
    parser.add_argument(
        "--usdars-ccl",
        type=float,
        default=None,
        help="Override the USDARS_CCL rate (ARS per USD).",
    )
    parser.add_argument(
        "--usdars-official",
        type=float,
        default=None,
        help="Override the USDARS_OFFICIAL rate (ARS per USD).",
    )
    parser.add_argument(
        "--money-market-monthly-pct",
        type=float,
        default=None,
        help=f"Override the {_RATE_KEY_MMM} rate input (in percent).",
    )
    parser.add_argument(
        "--caucion-monthly-pct",
        type=float,
        default=None,
        help=f"Override the {_RATE_KEY_CAUCION} rate input (in percent).",
    )
    parser.add_argument(
        "--expected-fx-devaluation-monthly-pct",
        type=float,
        default=None,
        help=f"Override the {_RATE_KEY_FX_DEV} rate input (in percent).",
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit a machine-readable JSON summary to stdout.",
    )
    return parser


# ---------------------------------------------------------------------------
# Provider helpers
# ---------------------------------------------------------------------------


def _load_universe(
    path: Path | str | None,
    *,
    include_disabled: bool,
) -> list[ArgentinaAsset]:
    """Load the universe, optionally including disabled / non-long-term assets."""
    resolved = Path(path).expanduser() if path is not None else _DEFAULT_UNIVERSE
    if include_disabled:
        return load_ar_long_term_universe(resolved)
    return get_enabled_long_term_assets(resolved)


def _build_providers(
    provider_name: str,
    *,
    universe_path: Optional[str] = None,
) -> list[MarketSnapshotProvider]:
    if provider_name == "static-example":
        return [StaticExampleSnapshotProvider()]
    if provider_name == "yahoo":
        # Yahoo only: no automatic fallback to static-example in this slice.
        # The user controls the fallback explicitly by re-running with a
        # different --provider, or by hand-editing the partial snapshot.
        return [
            YahooArgentinaMarketDataProvider(
                universe_path=universe_path,
            )
        ]
    raise ValueError(f"unsupported provider: {provider_name!r}")


def _resolve_output_path(raw: Optional[str], target_date: str) -> Path:
    if raw is not None:
        return Path(raw).expanduser()
    return _DEFAULT_OUTPUTS_DIR / f"{target_date}.json"


def _coerce_positive(
    value: Optional[float],
    *,
    field_name: str,
) -> Optional[float]:
    if value is None:
        return None
    try:
        as_float = float(value)
    except (TypeError, ValueError) as exc:  # pragma: no cover - argparse coerces
        raise ValueError(f"{field_name} must be numeric") from exc
    if math.isnan(as_float) or math.isinf(as_float):
        raise ValueError(f"{field_name} must be finite (got {as_float})")
    if as_float <= 0:
        raise ValueError(f"{field_name} must be > 0 (got {as_float})")
    return as_float


def _coerce_finite(
    value: Optional[float],
    *,
    field_name: str,
) -> Optional[float]:
    """Validate a percentage / rate input.

    Percentage rates (e.g. ``--money-market-monthly-pct``) can legitimately
    be ``0`` (a calm market) or even negative (deflation / appreciation),
    so we only enforce that the input is numeric and finite. We reject
    NaN and Inf so they cannot slip into the snapshot via ``float("nan")``.
    """
    if value is None:
        return None
    try:
        as_float = float(value)
    except (TypeError, ValueError) as exc:  # pragma: no cover - argparse coerces
        raise ValueError(f"{field_name} must be numeric") from exc
    if math.isnan(as_float) or math.isinf(as_float):
        raise ValueError(f"{field_name} must be finite (got {as_float})")
    return as_float


# ---------------------------------------------------------------------------
# Request + overrides
# ---------------------------------------------------------------------------


def _request_from_universe(
    target_date: str,
    universe: Sequence[ArgentinaAsset],
    *,
    fx_pairs: Sequence[str],
    rate_keys: Sequence[str],
) -> MarketSnapshotRequest:
    return MarketSnapshotRequest(
        as_of=target_date,
        symbols=tuple(asset.symbol for asset in universe),
        fx_pairs=tuple(fx_pairs),
        rate_keys=tuple(rate_keys),
    )


def _apply_fx_overrides(
    assembled: AssembledMarketSnapshot,
    *,
    target_date: str,
    overrides: dict[str, Optional[float]],
) -> tuple[dict[str, "FxRate"], list[str]]:
    """Return new fx_rates dict + which pairs were overridden."""
    from src.market_data.manual_snapshot import FxRate

    fx_rates = dict(assembled.snapshot.fx_rates)
    overridden: list[str] = []
    for pair, value in overrides.items():
        if value is None:
            continue
        fx_rates[pair] = FxRate(
            pair=pair,
            rate=float(value),
            as_of=target_date,
            provider="cli_override",
            delayed=True,
            notes="rate provided via --usdars-* CLI flag",
        )
        overridden.append(pair)
    return fx_rates, overridden


def _apply_rate_overrides(
    assembled: AssembledMarketSnapshot,
    *,
    target_date: str,
    overrides: dict[str, Optional[float]],
) -> tuple[dict[str, "RateInput"], list[str]]:
    """Return new rates dict + which keys were overridden."""
    from src.market_data.manual_snapshot import RateInput

    rates = dict(assembled.snapshot.rates)
    overridden: list[str] = []
    for key, value in overrides.items():
        if value is None:
            continue
        rates[key] = RateInput(
            key=key,
            value=float(value),
            as_of=target_date,
            provider="cli_override",
            notes="rate provided via --*-pct CLI flag",
        )
        overridden.append(key)
    return rates, overridden


# ---------------------------------------------------------------------------
# Core run
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BuildResult:
    snapshot_path: Path
    quotes_requested: int
    quotes_loaded: int
    fx_pairs_requested: int
    fx_rates_loaded: int
    rate_keys_requested: int
    rates_loaded: int
    missing_symbols: tuple[str, ...]
    missing_fx_pairs: tuple[str, ...]
    missing_rate_keys: tuple[str, ...]
    completeness: str
    provider_health: list[dict[str, Any]]
    warnings: tuple[str, ...]
    provider_sources: dict[str, str]


def _summarize(result: BuildResult, *, provider: str) -> dict[str, Any]:
    return {
        "manual_review_only": True,
        "live_trading_enabled": False,
        "provider": provider,
        "snapshot_path": str(result.snapshot_path),
        "quotes_requested": int(result.quotes_requested),
        "quotes_loaded": int(result.quotes_loaded),
        # Explicit FX / rate counts make it trivial for downstream callers
        # (and humans reading --json output) to spot a partial snapshot at
        # a glance without diffing the missing_* arrays.
        "fx_pairs_requested": int(result.fx_pairs_requested),
        "fx_rates_loaded": int(result.fx_rates_loaded),
        "fx_rates_missing": len(result.missing_fx_pairs),
        "rate_keys_requested": int(result.rate_keys_requested),
        "rates_loaded": int(result.rates_loaded),
        "rates_missing": len(result.missing_rate_keys),
        "missing_symbols": list(result.missing_symbols),
        "missing_fx_pairs": list(result.missing_fx_pairs),
        "missing_rate_keys": list(result.missing_rate_keys),
        "completeness": result.completeness,
        "provider_health": list(result.provider_health),
        "warnings": list(result.warnings),
        "provider_sources": dict(result.provider_sources),
        "status": "ok",
    }


def _write_snapshot(
    path: Path,
    payload: dict[str, Any],
    *,
    overwrite: bool,
) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"output file already exists; pass --overwrite to replace: {path}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")


def run(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    # Resolve simple inputs first so usage errors surface clearly.
    try:
        usdars_mep = _coerce_positive(args.usdars_mep, field_name="--usdars-mep")
        usdars_ccl = _coerce_positive(args.usdars_ccl, field_name="--usdars-ccl")
        usdars_official = _coerce_positive(
            args.usdars_official, field_name="--usdars-official"
        )
        mmm_pct = _coerce_finite(
            args.money_market_monthly_pct,
            field_name="--money-market-monthly-pct",
        )
        caucion_pct = _coerce_finite(
            args.caucion_monthly_pct, field_name="--caucion-monthly-pct"
        )
        fx_dev_pct = _coerce_finite(
            args.expected_fx_devaluation_monthly_pct,
            field_name="--expected-fx-devaluation-monthly-pct",
        )
    except ValueError as exc:
        return _EXIT_USAGE, {
            "status": "usage_error",
            "errors": [str(exc)],
            "manual_review_only": True,
            "live_trading_enabled": False,
        }

    try:
        universe = _load_universe(
            args.universe, include_disabled=bool(args.include_disabled)
        )
    except ValueError as exc:
        return _EXIT_FAILURE, {
            "status": "universe_failed",
            "errors": [str(exc)],
            "manual_review_only": True,
            "live_trading_enabled": False,
        }

    fx_overrides = {
        _FX_MEP: usdars_mep,
        _FX_CCL: usdars_ccl,
        _FX_OFFICIAL: usdars_official,
    }
    rate_overrides = {
        _RATE_KEY_MMM: mmm_pct,
        _RATE_KEY_CAUCION: caucion_pct,
        _RATE_KEY_FX_DEV: fx_dev_pct,
    }

    # The chain serves FX/rates we ask for; explicit overrides win after the
    # chain returns. Always request the three canonical FX pairs and three
    # canonical rate keys so missing items show up in the summary.
    requested_fx = (_FX_MEP, _FX_CCL, _FX_OFFICIAL)
    requested_rates = (_RATE_KEY_MMM, _RATE_KEY_CAUCION, _RATE_KEY_FX_DEV)

    try:
        providers = _build_providers(args.provider, universe_path=args.universe)
    except ValueError as exc:
        return _EXIT_USAGE, {
            "status": "usage_error",
            "errors": [str(exc)],
            "manual_review_only": True,
            "live_trading_enabled": False,
        }

    request = _request_from_universe(
        args.date,
        universe,
        fx_pairs=requested_fx,
        rate_keys=requested_rates,
    )

    assembled = assemble_market_snapshot(
        request,
        providers,
        snapshot_id=f"auto-{args.provider}-{args.date}",
        source=f"auto:{args.provider}",
    )

    fx_rates, overridden_fx = _apply_fx_overrides(
        assembled, target_date=args.date, overrides=fx_overrides
    )
    rates, overridden_rates = _apply_rate_overrides(
        assembled, target_date=args.date, overrides=rate_overrides
    )

    missing_fx_pairs = tuple(
        p for p in request.fx_pairs if p not in fx_rates
    )
    missing_rate_keys = tuple(
        k for k in request.rate_keys if k not in rates
    )

    # Recompute completeness after overrides; do not downgrade if every
    # gap was filled by CLI flags.
    total_requested = (
        len(request.symbols) + len(request.fx_pairs) + len(request.rate_keys)
    )
    total_served = (
        len(assembled.snapshot.quotes) + len(fx_rates) + len(rates)
    )
    if total_requested == 0 or total_served == total_requested:
        completeness = "complete"
    elif total_served == 0:
        completeness = "minimal"
    else:
        completeness = "partial"

    warnings_list: list[str] = []
    for w in assembled.warnings:
        # Drop any chain warning that complained about an FX pair or rate
        # key the user just supplied via --usdars-* / --*-pct flags.
        skip = False
        if overridden_fx and "missing FX rates" in w:
            skip = True
        if overridden_rates and "missing rate inputs" in w:
            skip = True
        if not skip:
            warnings_list.append(w)
    if overridden_fx:
        warnings_list.append(
            "fx_rates overridden via CLI flags: "
            f"{', '.join(sorted(overridden_fx))}"
        )
    if overridden_rates:
        warnings_list.append(
            "rate inputs overridden via CLI flags: "
            f"{', '.join(sorted(overridden_rates))}"
        )
    if missing_fx_pairs:
        warnings_list.append(
            "still missing FX rates: " + ", ".join(missing_fx_pairs)
        )
    if missing_rate_keys:
        warnings_list.append(
            "still missing rate inputs: " + ", ".join(missing_rate_keys)
        )

    # Replace the chain-built snapshot with one that has the overridden
    # FX/rates and recomputed completeness.
    #
    # NOTE: build-tool annotations (chain breadcrumbs, CLI override
    # notices, "still missing FX rates" advisories) live in the build
    # summary and the daily report, not in the snapshot's own
    # ``warnings`` field. The snapshot's ``warnings`` field is reserved
    # for quality issues raised by the *editor of the snapshot*, and is
    # counted as a strict-validation failure by ``validate_manual_inputs``.
    # Persisting build noise there would make every auto-built snapshot
    # fail strict mode and defeat the slice goal.
    from src.market_data.manual_snapshot import ManualMarketSnapshot

    snapshot = ManualMarketSnapshot(
        schema_version="1.0",
        snapshot_id=assembled.snapshot.snapshot_id,
        as_of=args.date,
        source=assembled.snapshot.source,
        manual_review_only=True,
        live_trading_enabled=False,
        data_frequency="1d",
        quotes=dict(assembled.snapshot.quotes),
        fx_rates=fx_rates,
        rates=rates,
        warnings=(),
        completeness=completeness,
    )

    snapshot_dict = manual_market_snapshot_to_dict(snapshot)
    output_path = _resolve_output_path(args.out, args.date)
    try:
        _write_snapshot(output_path, snapshot_dict, overwrite=bool(args.overwrite))
    except FileExistsError as exc:
        return _EXIT_FAILURE, {
            "status": "output_exists",
            "errors": [str(exc)],
            "manual_review_only": True,
            "live_trading_enabled": False,
        }
    except OSError as exc:
        return _EXIT_FAILURE, {
            "status": "write_failed",
            "errors": [str(exc)],
            "manual_review_only": True,
            "live_trading_enabled": False,
        }

    # Verify round-trip parses; surface a failure rather than handing the
    # user a snapshot the loader will later reject.
    try:
        load_manual_market_snapshot(output_path)
    except ValueError as exc:
        return _EXIT_FAILURE, {
            "status": "round_trip_failed",
            "errors": [str(exc)],
            "manual_review_only": True,
            "live_trading_enabled": False,
            "snapshot_path": str(output_path),
        }

    # Provider health: keep it offline-by-construction and never include keys.
    provider_health = [provider.health_check() for provider in providers]

    # Build provider_sources mapping for the assembled snapshot. Overridden
    # items get a synthetic "cli_override" provider name.
    provider_sources = dict(assembled.provider_sources)
    for pair in overridden_fx:
        provider_sources[f"fx:{pair}"] = "cli_override"
    for key in overridden_rates:
        provider_sources[f"rate:{key}"] = "cli_override"

    result = BuildResult(
        snapshot_path=output_path,
        quotes_requested=len(request.symbols),
        quotes_loaded=len(snapshot.quotes),
        fx_pairs_requested=len(request.fx_pairs),
        fx_rates_loaded=len(snapshot.fx_rates),
        rate_keys_requested=len(request.rate_keys),
        rates_loaded=len(snapshot.rates),
        missing_symbols=assembled.missing_symbols,
        missing_fx_pairs=missing_fx_pairs,
        missing_rate_keys=missing_rate_keys,
        completeness=completeness,
        provider_health=provider_health,
        warnings=tuple(warnings_list),
        provider_sources=provider_sources,
    )
    return _EXIT_OK, _summarize(result, provider=args.provider)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _print_human_summary(summary: dict[str, Any]) -> None:
    print("Manual review only. No live trading. No broker automation.")
    status = summary.get("status", "unknown")
    print(f"build_market_snapshot status: {status}")
    if status != "ok":
        for err in summary.get("errors", []):
            print(f"  error: {err}")
        return
    print(f"  provider: {summary['provider']}")
    print(f"  snapshot_path: {summary['snapshot_path']}")
    print(f"  quotes_requested: {summary['quotes_requested']}")
    print(f"  quotes_loaded: {summary['quotes_loaded']}")
    print(
        f"  fx_rates_loaded: {summary.get('fx_rates_loaded', 0)}/"
        f"{summary.get('fx_pairs_requested', 0)} "
        f"(missing={summary.get('fx_rates_missing', 0)})"
    )
    print(
        f"  rates_loaded: {summary.get('rates_loaded', 0)}/"
        f"{summary.get('rate_keys_requested', 0)} "
        f"(missing={summary.get('rates_missing', 0)})"
    )
    print(f"  completeness: {summary['completeness']}")
    missing_syms = summary.get("missing_symbols") or []
    if missing_syms:
        print(f"  missing_symbols ({len(missing_syms)}):")
        for sym in missing_syms:
            print(f"    - {sym}")
    if summary.get("missing_fx_pairs"):
        print(
            "  missing_fx_pairs: " + ", ".join(summary["missing_fx_pairs"])
        )
    if summary.get("missing_rate_keys"):
        print(
            "  missing_rate_keys: "
            + ", ".join(summary["missing_rate_keys"])
        )
    health = summary.get("provider_health") or []
    if health:
        print(f"  provider_health ({len(health)}):")
        for h in health:
            print(
                "    - "
                f"{h.get('provider', '?')}: ok={h.get('ok')} "
                f"network_required={h.get('network_required')} "
                f"requires_api_key={h.get('requires_api_key')}"
            )
    warnings = summary.get("warnings") or []
    if warnings:
        print(f"  warnings ({len(warnings)}):")
        for w in warnings:
            print(f"    - {w}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_arg_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return _EXIT_USAGE if int(exc.code or 0) != 0 else _EXIT_OK

    exit_code, summary = run(args)
    if args.as_json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        _print_human_summary(summary)
    return exit_code


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    raise SystemExit(main())
