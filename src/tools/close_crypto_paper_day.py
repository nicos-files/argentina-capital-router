from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from src.execution.crypto_paper_daily_close import close_crypto_paper_day
from src.market_data.providers import BinanceSpotMarketDataProvider


def run_close_crypto_paper_day(
    *,
    run_id: str,
    base_path: str = "runs",
    artifacts_dir: str | None = None,
    output_dir: str | None = None,
    prices_json: str | None = None,
    as_of: str | None = None,
    provider: Any | None = None,
) -> dict[str, Any]:
    if not _flag("ENABLE_CRYPTO_PAPER_CLOSE"):
        return {"status": "SKIPPED", "reason": "crypto_paper_close_disabled"}

    artifact_root = Path(artifacts_dir) if artifacts_dir else Path(base_path) / run_id / "artifacts" / "crypto_paper"
    target_output = Path(output_dir) if output_dir else artifact_root / "daily_close"
    effective_as_of = _parse_datetime(as_of) or datetime.utcnow()
    injected_prices = _load_prices_json(prices_json)

    active_provider = None
    provider_health: dict[str, Any] = {}
    if injected_prices is None and _flag("ENABLE_CRYPTO_MARKET_DATA"):
        active_provider = provider or BinanceSpotMarketDataProvider()
        health = active_provider.health_check()
        provider_health = {
            "provider_name": health.provider_name,
            "status": health.status,
            "message": health.message,
            "checked_at_utc": health.checked_at_utc,
        }
    elif injected_prices is None:
        provider_health = {
            "provider_name": "none",
            "status": "unavailable",
            "message": "market data disabled; used last known prices when needed",
            "checked_at_utc": effective_as_of.isoformat(),
        }

    result = close_crypto_paper_day(
        artifacts_dir=artifact_root,
        as_of=effective_as_of,
        output_dir=target_output,
        price_map=injected_prices,
        provider=active_provider,
        provider_health=provider_health,
    )
    return {
        "status": "SUCCESS",
        "warnings": list(result.warnings),
        "artifacts": dict(result.artifacts_written),
        "ending_equity": result.performance.ending_equity,
        "total_pnl": result.performance.total_pnl,
    }


def _load_prices_json(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        return payload
    raise ValueError("prices-json must contain a JSON object")


def _flag(name: str) -> bool:
    value = str(os.getenv(name) or "").strip().lower()
    return value in {"1", "true", "yes", "y", "si", "s"}


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Close crypto paper day from isolated crypto paper artifacts.")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--base-path", default="runs")
    parser.add_argument("--artifacts-dir")
    parser.add_argument("--output-dir")
    parser.add_argument("--prices-json")
    parser.add_argument("--as-of")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = run_close_crypto_paper_day(
        run_id=args.run_id,
        base_path=args.base_path,
        artifacts_dir=args.artifacts_dir,
        output_dir=args.output_dir,
        prices_json=args.prices_json,
        as_of=args.as_of,
    )
    print("[CLOSE-CRYPTO-PAPER-DAY]")
    print(f"- status: {result['status']}")
    if result["status"] == "SUCCESS":
        print(f"- ending_equity: {result['ending_equity']:.6f}")
        print(f"- total_pnl: {result['total_pnl']:.6f}")
        print(f"- artifacts: {result['artifacts']}")
    else:
        print(f"- reason: {result.get('reason')}")


if __name__ == "__main__":
    main()
