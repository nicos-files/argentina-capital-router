from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from src.decision_intel.contracts.recommendations.recommendation_models import RecommendationOutput
from src.engines import EngineContext, IntradayCryptoEngine
from src.execution.crypto_paper_executor import CryptoPaperExecutor, load_crypto_paper_ledger, write_crypto_paper_execution_artifacts
from src.execution.crypto_paper_exits import evaluate_crypto_exit_triggers
from src.execution.crypto_paper_models import CryptoPaperExecutionConfig
from src.market_data.crypto_symbols import enabled_crypto_symbols, load_crypto_universe_config
from src.market_data.providers import BinanceSpotMarketDataProvider


ROOT = Path(__file__).resolve().parents[2]
CRYPTO_UNIVERSE_PATH = ROOT / "config" / "market_universe" / "crypto.json"


def run_crypto_paper(
    run_id: str,
    base_path: str = "runs",
    provider: Any | None = None,
    engine: IntradayCryptoEngine | None = None,
    executor: CryptoPaperExecutor | None = None,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    if not _flag("ENABLE_CRYPTO_PAPER_EXECUTION"):
        return {"status": "SKIPPED", "reason": "crypto_paper_execution_disabled"}
    if not _flag("ENABLE_CRYPTO_MARKET_DATA"):
        return {"status": "SKIPPED", "reason": "crypto_market_data_disabled"}

    crypto_config = load_crypto_universe_config(CRYPTO_UNIVERSE_PATH) if CRYPTO_UNIVERSE_PATH.exists() else {}
    crypto_universe = list(crypto_config.get("symbols") or [])
    strategy_config = dict(crypto_config.get("strategy") or {})
    now = as_of or datetime.utcnow()
    active_provider = provider or BinanceSpotMarketDataProvider()
    health = active_provider.health_check()
    active_config = CryptoPaperExecutionConfig(enable_exits=_flag("ENABLE_CRYPTO_PAPER_EXITS"))
    context = EngineContext(
        as_of=now,
        run_id=run_id,
        mode="crypto_paper",
        universe=enabled_crypto_symbols(crypto_universe),
        config={
            "crypto_universe_path": str(CRYPTO_UNIVERSE_PATH) if CRYPTO_UNIVERSE_PATH.exists() else None,
            "crypto_universe": crypto_universe,
            "crypto_symbols": enabled_crypto_symbols(crypto_universe),
            "crypto_strategy": strategy_config,
            "enable_crypto_market_data": True,
        },
        provider_health={
            active_provider.provider_name: {
                "status": health.status,
                "message": health.message,
                "checked_at_utc": health.checked_at_utc,
            }
        },
        metadata={
            "asof_date": now.strftime("%Y-%m-%d"),
            "execution_date": now.strftime("%Y-%m-%d"),
            "execution_hour": now.strftime("%H%M"),
            "crypto_provider_name": active_provider.provider_name,
            "crypto_provider": active_provider,
        },
    )
    active_engine = engine or IntradayCryptoEngine()
    engine_result = active_engine.run(context)
    active_executor = executor or CryptoPaperExecutor(active_config)
    active_ledger = load_crypto_paper_ledger(run_id=run_id, base_path=base_path, config=active_config) if _flag("ENABLE_CRYPTO_PAPER_EXITS") else None

    latest_quotes = {}
    for item in engine_result.recommendations.recommendations:
        latest_quotes[item.asset_id] = {
            "last_price": item.price_used,
            "ask": item.price_used,
            "provider": item.extensions.get("provider"),
        }

    exit_events = []
    if _flag("ENABLE_CRYPTO_PAPER_EXITS") and active_ledger is not None:
        candles_by_symbol: dict[str, Any] = {}
        for symbol, position in active_ledger.positions.items():
            try:
                candles_by_symbol[symbol] = active_provider.get_historical_bars(
                    symbol=symbol,
                    timeframe=str(strategy_config.get("timeframe", "5m")),
                    limit=int(strategy_config.get("lookback_limit", 120)),
                )
                latest_quotes.setdefault(symbol, active_provider.get_latest_quote(symbol))
            except Exception:
                continue
        exit_events = evaluate_crypto_exit_triggers(
            positions=list(active_ledger.positions.values()),
            candles_by_symbol=candles_by_symbol,
            as_of=now,
            config=active_config,
        )

    execution_result = active_executor.execute(
        recommendations=engine_result.recommendations,
        latest_quotes=latest_quotes,
        as_of=now,
        ledger=active_ledger,
        exit_events=exit_events,
    )
    artifacts = write_crypto_paper_execution_artifacts(run_id=run_id, result=execution_result, base_path=base_path)
    return {
        "status": "SUCCESS",
        "artifacts": {name: str(path) for name, path in artifacts.items()},
        "recommendation_count": len(engine_result.recommendations.recommendations),
        "fill_count": len(execution_result.fills),
        "exit_count": len(execution_result.exit_events),
    }


def _flag(name: str) -> bool:
    value = str(os.getenv(name) or "").strip().lower()
    return value in {"1", "true", "yes", "y", "si", "s"}


def main() -> None:
    now = datetime.utcnow()
    run_id = now.strftime("%Y%m%d-%H%M")
    result = run_crypto_paper(run_id=run_id, as_of=now)
    print(f"[CRYPTO-PAPER] {result}")


if __name__ == "__main__":
    main()
