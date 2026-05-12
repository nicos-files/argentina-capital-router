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
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit a machine-readable JSON summary instead of human text.",
    )
    return parser


def _load_market(path: Path) -> tuple[Optional[ManualMarketSnapshot], list[str]]:
    errors: list[str] = []
    try:
        snapshot = load_manual_market_snapshot(path)
    except (ValueError, FileNotFoundError) as exc:
        errors.append(f"market snapshot invalid: {exc}")
        return None, errors
    return snapshot, errors


def _load_portfolio(
    path: Path,
) -> tuple[Optional[ManualPortfolioSnapshot], list[str]]:
    errors: list[str] = []
    try:
        snapshot = load_manual_portfolio_snapshot(path)
    except (ValueError, FileNotFoundError) as exc:
        errors.append(f"portfolio snapshot invalid: {exc}")
        return None, errors
    return snapshot, errors


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

    market: Optional[ManualMarketSnapshot] = None
    if args.market_snapshot:
        market_path = Path(args.market_snapshot).expanduser()
        market, m_errors = _load_market(market_path)
        errors.extend(m_errors)
        market_entry: dict[str, Any] = {
            "path": str(market_path),
            "loaded": market is not None,
        }
        if market is not None:
            market_entry["summary"] = summarize_snapshot(market)
        summary["market"] = market_entry

    portfolio: Optional[ManualPortfolioSnapshot] = None
    if args.portfolio_snapshot:
        portfolio_path = Path(args.portfolio_snapshot).expanduser()
        portfolio, p_errors = _load_portfolio(portfolio_path)
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

    strict_failures: list[str] = []
    if args.strict:
        strict_failures = _evaluate_strict(market, portfolio, valuation)
        summary["strict_failures"] = strict_failures

    summary["status"] = "valid"
    if strict_failures:
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
