"""CLI wrapper around :func:`src.execution.binance_testnet_executor.run_binance_testnet_execution`.

Examples:

    # Order-test mode (default — Binance no-op validator, no real testnet
    # order placed). Requires ENABLE_BINANCE_TESTNET_EXECUTION=1 and valid
    # testnet credentials.
    PYTHONPATH=. python -m src.tools.run_binance_testnet_execution \\
        --paper-artifacts-dir artifacts/crypto_paper

    # Real testnet placement mode. Both env flags required:
    #   ENABLE_BINANCE_TESTNET_EXECUTION=1
    #   BINANCE_TESTNET_ORDER_TEST_ONLY=0
    BINANCE_TESTNET_ORDER_TEST_ONLY=0 PYTHONPATH=. python -m \\
        src.tools.run_binance_testnet_execution \\
        --paper-artifacts-dir artifacts/crypto_paper

The CLI never reads live Binance credentials, never speaks to live hosts,
and never auto-places live orders.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.execution.binance_testnet_executor import (
    ALLOWED_SYMBOLS_ENV,
    BASE_URL_ENV,
    ENABLE_FLAG,
    MAX_NOTIONAL_ENV,
    ORDER_TEST_ONLY_FLAG,
    run_binance_testnet_execution,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Mirror crypto paper-forward semantic events to the Binance Spot "
            "Testnet. Disabled unless ENABLE_BINANCE_TESTNET_EXECUTION=1; in "
            "order-test mode by default (no real order placed)."
        )
    )
    parser.add_argument(
        "--paper-artifacts-dir",
        required=True,
        help="Crypto paper-forward artifacts root (read-only).",
    )
    parser.add_argument(
        "--testnet-artifacts-dir",
        default=None,
        help=(
            "Override target directory for testnet artifacts. "
            "Defaults to <paper_artifacts_dir>/../crypto_testnet."
        ),
    )
    parser.add_argument(
        "--rebuild-semantic",
        action="store_true",
        help="Force rebuild of the semantic layer from source paper artifacts.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Run all gating logic and write artifacts but do NOT call the "
            "broker, even if credentials and the enable flag are set."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_binance_testnet_execution(
        paper_artifacts_dir=args.paper_artifacts_dir,
        testnet_artifacts_dir=args.testnet_artifacts_dir,
        rebuild_semantic=bool(args.rebuild_semantic),
        dry_run=bool(args.dry_run),
    )
    audit = {
        "ok": result.get("ok"),
        "testnet": result.get("testnet"),
        "live_trading": result.get("live_trading"),
        "dry_run": result.get("dry_run"),
        "order_test_only": result.get("order_test_only"),
        "base_url": result.get("base_url"),
        "max_notional": result.get("max_notional"),
        "allowed_symbols": result.get("allowed_symbols"),
        "considered_count": result.get("considered_count"),
        "placed_count": result.get("placed_count"),
        "test_ok_count": result.get("test_ok_count"),
        "rejected_count": result.get("rejected_count"),
        "skipped_count": result.get("skipped_count"),
        "api_key_masked": result.get("api_key_masked"),
        "testnet_artifacts_dir": result.get("testnet_artifacts_dir"),
        "reason": result.get("reason"),
        "warnings": result.get("warnings"),
        "env_flags": {
            ENABLE_FLAG: "must be '1' to enable testnet execution",
            ORDER_TEST_ONLY_FLAG: "default '1' (order/test); set '0' to place",
            BASE_URL_ENV: "must be a testnet host",
            MAX_NOTIONAL_ENV: "default 25.0 USDT",
            ALLOWED_SYMBOLS_ENV: "comma-separated allowlist",
        },
    }
    sys.stdout.write(json.dumps(audit, sort_keys=True) + "\n")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main(sys.argv[1:]))
