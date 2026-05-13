"""CLI to validate manual market and/or portfolio snapshots.

Manual review only. No network. No broker. No live trading. No orders.

The validator:
- loads the provided snapshot(s) using the same loaders the daily plan tool uses
- if both are provided, also runs the portfolio valuation against the market
  snapshot so the user can see what would and wouldn't price under their inputs
- in ``--strict`` mode, fails on incomplete/partial snapshots, on quality
  warnings, on missing position prices, or on ARS amounts that cannot be
  converted because of a missing FX rate
- never writes ``execution.plan`` or ``final_decision.json``; in fact it never
  writes any artifact at all
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

from src.market_data.ar_symbols import (
    ArgentinaAsset,
    load_ar_long_term_universe,
)
from src.market_data.manual_snapshot import (
    ManualMarketSnapshot,
    load_manual_market_snapshot,
    summarize_snapshot,
)
from src.portfolio.portfolio_state import (
    ManualPortfolioSnapshot,
    load_manual_portfolio_snapshot,
    summarize_portfolio_snapshot,
)
from src.portfolio.portfolio_valuation import (
    MISSING_FX,
    MISSING_PRICE,
    PortfolioValuation,
    value_portfolio,
)
from src.quality.input_quality import (
    InputQualityReport,
    combine_quality_reports,
    validate_market_snapshot_quality,
    validate_portfolio_snapshot_quality,
)


_EXIT_OK = 0
_EXIT_INVALID = 1
_EXIT_USAGE = 2


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate manual market and/or portfolio snapshots. Manual review "
            "only - no live trading, no broker, no orders, no network."
        )
    )
    parser.add_argument(
        "--market-snapshot",
        default=None,
        help="Path to a manual market snapshot JSON file.",
    )
    parser.add_argument(
        "--portfolio-snapshot",
        default=None,
        help="Path to a manual portfolio snapshot JSON file.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Strict mode: fail if completeness != 'complete', if any quality "
            "warnings exist, if any portfolio position lacks a price, or if any "
            "ARS amount cannot be converted to USD."
        ),
    )
    parser.add_argument(
        "--expected-date",
        default=None,
        help=(
            "Optional expected as-of date (YYYY-MM-DD). When provided, the "
            "quality checks fail if snapshot dates differ from this value "
            "and ``--strict`` is set."
        ),
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit a machine-readable JSON summary instead of human text.",
    )
    return parser


def _read_raw_json(path: Path) -> tuple[Optional[dict[str, Any]], list[str]]:
    """Read a JSON file as a raw dict without applying loader invariants.

    The quality checks need to scan the raw shape for TODO markers and
    placeholder values before the schema loaders normalize the data.
    """
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError as exc:
        return None, [f"snapshot file not found: {exc}"]
    except json.JSONDecodeError as exc:
        return None, [f"{path}: invalid JSON: {exc}"]
    if not isinstance(data, dict):
        return None, [f"{path}: top-level value must be a JSON object"]
    return data, []


def _load_market(
    path: Path,
) -> tuple[Optional[ManualMarketSnapshot], Optional[dict[str, Any]], list[str]]:
    raw, raw_errors = _read_raw_json(path)
    if raw_errors:
        return None, raw, [f"market snapshot invalid: {err}" for err in raw_errors]
    try:
        snapshot = load_manual_market_snapshot(path)
    except (ValueError, FileNotFoundError) as exc:
        return None, raw, [f"market snapshot invalid: {exc}"]
    return snapshot, raw, []


def _load_portfolio(
    path: Path,
) -> tuple[
    Optional[ManualPortfolioSnapshot], Optional[dict[str, Any]], list[str]
]:
    raw, raw_errors = _read_raw_json(path)
    if raw_errors:
        return None, raw, [
            f"portfolio snapshot invalid: {err}" for err in raw_errors
        ]
    try:
        snapshot = load_manual_portfolio_snapshot(path)
    except (ValueError, FileNotFoundError) as exc:
        return None, raw, [f"portfolio snapshot invalid: {exc}"]
    return snapshot, raw, []


def _safe_load_universe() -> list[ArgentinaAsset]:
    """Load the configured universe; return [] if it cannot be loaded.

    A missing or invalid universe file is not a hard failure for this CLI
    (the symbol coverage check just becomes a no-op). The default path is
    already used by the rest of the codebase.
    """
    try:
        return load_ar_long_term_universe()
    except (ValueError, FileNotFoundError):  # pragma: no cover - defensive
        return []


def _valuation_summary(valuation: PortfolioValuation) -> dict[str, Any]:
    missing_prices = sorted(
        p.symbol
        for p in valuation.positions
        if p.valuation_status == MISSING_PRICE
    )
    missing_fx_positions = sorted(
        p.symbol
        for p in valuation.positions
        if p.valuation_status == MISSING_FX
    )
    missing_fx_cash = sorted(
        c.currency
        for c in valuation.cash
        if c.valuation_status == MISSING_FX
    )
    return {
        "total_value_usd": float(valuation.total_value_usd),
        "positions_priced": sum(
            1 for p in valuation.positions if p.market_value is not None
        ),
        "positions_missing_price": missing_prices,
        "positions_missing_fx": missing_fx_positions,
        "cash_missing_fx": missing_fx_cash,
        "warnings": list(valuation.warnings),
    }


def _evaluate_strict(
    market: Optional[ManualMarketSnapshot],
    portfolio: Optional[ManualPortfolioSnapshot],
    valuation: Optional[PortfolioValuation],
) -> list[str]:
    failures: list[str] = []
    if market is not None:
        if market.completeness != "complete":
            failures.append(
                f"market snapshot completeness is {market.completeness!r}, expected 'complete'"
            )
        if market.warnings:
            failures.append(
                f"market snapshot has {len(market.warnings)} quality warning(s)"
            )
    if portfolio is not None:
        if portfolio.completeness != "complete":
            failures.append(
                f"portfolio snapshot completeness is {portfolio.completeness!r}, expected 'complete'"
            )
        if portfolio.warnings:
            failures.append(
                f"portfolio snapshot has {len(portfolio.warnings)} quality warning(s)"
            )
    if valuation is not None:
        missing_prices = [
            p.symbol
            for p in valuation.positions
            if p.valuation_status == MISSING_PRICE
        ]
        if missing_prices:
            failures.append(
                "portfolio positions missing price in market snapshot: "
                + ", ".join(sorted(missing_prices))
            )
        missing_fx = [
            p.symbol
            for p in valuation.positions
            if p.valuation_status == MISSING_FX
        ]
        if missing_fx:
            failures.append(
                "portfolio positions cannot be converted (missing FX): "
                + ", ".join(sorted(missing_fx))
            )
        missing_fx_cash = [
            c.currency
            for c in valuation.cash
            if c.valuation_status == MISSING_FX
        ]
        if missing_fx_cash:
            failures.append(
                "cash balances cannot be converted (missing FX): "
                + ", ".join(sorted(missing_fx_cash))
            )
    return failures


def _print_text_report(summary: dict[str, Any]) -> None:
    print("Manual review only. No live trading. No broker automation.")
    print(f"Validation status: {summary['status']}")
    if summary.get("errors"):
        print("Errors:")
        for err in summary["errors"]:
            print(f"  - {err}")
    market = summary.get("market")
    if market is not None:
        print("Market snapshot:")
        print(f"  path: {market['path']}")
        if market.get("loaded"):
            s = market["summary"]
            print(f"  snapshot_id: {s['snapshot_id']}")
            print(f"  as_of: {s['as_of']}")
            print(f"  completeness: {s['completeness']}")
            print(
                "  loaded: "
                f"{s['quotes_loaded']} quote(s), {s['fx_rates_loaded']} fx, "
                f"{s['rates_loaded']} rate(s)"
            )
            if s.get("warnings"):
                print(f"  warnings ({len(s['warnings'])}):")
                for w in s["warnings"]:
                    print(f"    - {w}")
    portfolio = summary.get("portfolio")
    if portfolio is not None:
        print("Portfolio snapshot:")
        print(f"  path: {portfolio['path']}")
        if portfolio.get("loaded"):
            s = portfolio["summary"]
            print(f"  snapshot_id: {s['snapshot_id']}")
            print(f"  as_of: {s['as_of']}")
            print(f"  completeness: {s['completeness']}")
            print(
                "  loaded: "
                f"{s['positions_loaded']} position(s), "
                f"{s['cash_balances_loaded']} cash balance(s)"
            )
            if s.get("warnings"):
                print(f"  warnings ({len(s['warnings'])}):")
                for w in s["warnings"]:
                    print(f"    - {w}")
    valuation = summary.get("valuation")
    if valuation is not None:
        print("Valuation:")
        print(f"  total_value_usd: {valuation['total_value_usd']:.2f}")
        print(f"  positions_priced: {valuation['positions_priced']}")
        if valuation["positions_missing_price"]:
            print(
                "  positions_missing_price: "
                + ", ".join(valuation["positions_missing_price"])
            )
        if valuation["positions_missing_fx"]:
            print(
                "  positions_missing_fx: "
                + ", ".join(valuation["positions_missing_fx"])
            )
        if valuation["cash_missing_fx"]:
            print(
                "  cash_missing_fx: "
                + ", ".join(valuation["cash_missing_fx"])
            )
        if valuation["warnings"]:
            print(f"  warnings ({len(valuation['warnings'])}):")
            for w in valuation["warnings"]:
                print(f"    - {w}")
    quality = summary.get("quality")
    if isinstance(quality, dict):
        print("Input quality:")
        print(f"  ok: {quality.get('ok')}")
        print(f"  strict: {quality.get('strict')}")
        print(f"  errors: {quality.get('errors_count', 0)}")
        print(f"  warnings: {quality.get('warnings_count', 0)}")
        print(f"  infos: {quality.get('infos_count', 0)}")
        issues = quality.get("issues") or []
        if issues:
            print(f"  issues ({len(issues)}):")
            for issue in issues:
                severity = issue.get("severity", "?")
                code = issue.get("code", "?")
                path = issue.get("path") or "-"
                message = issue.get("message", "")
                print(f"    - [{severity}] {code} ({path}): {message}")
    if summary.get("strict_failures"):
        print("Strict-mode failures:")
        for f in summary["strict_failures"]:
            print(f"  - {f}")


def run(args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    """Run validation; return (exit_code, machine-readable summary)."""
    if not args.market_snapshot and not args.portfolio_snapshot:
        return _EXIT_USAGE, {
            "status": "usage_error",
            "errors": [
                "at least one of --market-snapshot or --portfolio-snapshot is required"
            ],
            "manual_review_only": True,
            "live_trading_enabled": False,
        }

    errors: list[str] = []
    summary: dict[str, Any] = {
        "manual_review_only": True,
        "live_trading_enabled": False,
        "strict": bool(args.strict),
    }
    if args.expected_date:
        summary["expected_date"] = str(args.expected_date)

    market: Optional[ManualMarketSnapshot] = None
    raw_market: Optional[dict[str, Any]] = None
    if args.market_snapshot:
        market_path = Path(args.market_snapshot).expanduser()
        market, raw_market, m_errors = _load_market(market_path)
        errors.extend(m_errors)
        market_entry: dict[str, Any] = {
            "path": str(market_path),
            "loaded": market is not None,
        }
        if market is not None:
            market_entry["summary"] = summarize_snapshot(market)
        summary["market"] = market_entry

    portfolio: Optional[ManualPortfolioSnapshot] = None
    raw_portfolio: Optional[dict[str, Any]] = None
    if args.portfolio_snapshot:
        portfolio_path = Path(args.portfolio_snapshot).expanduser()
        portfolio, raw_portfolio, p_errors = _load_portfolio(portfolio_path)
        errors.extend(p_errors)
        portfolio_entry: dict[str, Any] = {
            "path": str(portfolio_path),
            "loaded": portfolio is not None,
        }
        if portfolio is not None:
            portfolio_entry["summary"] = summarize_portfolio_snapshot(portfolio)
        summary["portfolio"] = portfolio_entry

    valuation: Optional[PortfolioValuation] = None
    if portfolio is not None and market is not None:
        valuation = value_portfolio(portfolio, market_snapshot=market)
        summary["valuation"] = _valuation_summary(valuation)

    if errors:
        summary["status"] = "invalid"
        summary["errors"] = errors
        return _EXIT_INVALID, summary

    # Quality checks (TODO markers, placeholder values, date mismatches,
    # unknown symbols, missing FX, missing position prices, completeness).
    universe = _safe_load_universe() if (market or portfolio) else []
    reports: list[InputQualityReport] = []
    if market is not None:
        reports.append(
            validate_market_snapshot_quality(
                raw_market_data=raw_market,
                market_snapshot=market,
                expected_date=args.expected_date,
                universe_assets=universe,
                strict=False,
            )
        )
    if portfolio is not None:
        reports.append(
            validate_portfolio_snapshot_quality(
                raw_portfolio_data=raw_portfolio,
                portfolio_snapshot=portfolio,
                expected_date=args.expected_date,
                market_snapshot=market,
                universe_assets=universe,
                strict=False,
            )
        )
    quality_report = combine_quality_reports(*reports, strict=bool(args.strict))
    summary["quality"] = quality_report.to_dict()

    strict_failures: list[str] = []
    if args.strict:
        strict_failures = _evaluate_strict(market, portfolio, valuation)
        summary["strict_failures"] = strict_failures

    summary["status"] = "valid"
    if strict_failures or (args.strict and not quality_report.ok):
        summary["status"] = "strict_failed"
        return _EXIT_INVALID, summary
    return _EXIT_OK, summary


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    exit_code, summary = run(args)
    if args.as_json:
        print(json.dumps(summary, indent=2, sort_keys=True))
    else:
        _print_text_report(summary)
    return exit_code


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    raise SystemExit(main())
