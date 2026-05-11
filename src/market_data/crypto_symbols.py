from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CRYPTO_UNIVERSE_PATH = ROOT / "config" / "market_universe" / "crypto.json"
KNOWN_CRYPTO_BASES = {"BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE"}


def normalize_crypto_symbol(symbol: str, exchange: str = "binance_spot") -> str:
    text = str(symbol or "").strip().upper()
    if not text:
        return ""
    if exchange != "binance_spot":
        return text

    compact = text.replace("/", "").replace("-", "").replace("_", "")
    if compact in {"BTCUSD", "ETHUSD", "SOLUSD", "BNBUSD", "XRPUSD", "ADAUSD", "DOGEUSD"}:
        return compact.replace("USD", "USDT")
    return compact


def load_crypto_universe(path: str | Path | None = None) -> list[dict[str, Any]]:
    config = load_crypto_universe_config(path)
    return list(config.get("symbols") or [])


def load_crypto_universe_config(path: str | Path | None = None) -> dict[str, Any]:
    target = Path(path) if path is not None else DEFAULT_CRYPTO_UNIVERSE_PATH
    if not target.exists():
        return {}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    symbols = payload.get("symbols")
    if not isinstance(symbols, list):
        return {}

    default_quote = str(payload.get("default_quote_currency") or "USDT").strip().upper() or "USDT"
    normalized: list[dict[str, Any]] = []
    for item in symbols:
        if not isinstance(item, dict):
            continue
        symbol = normalize_crypto_symbol(item.get("symbol", ""), exchange=str(item.get("exchange") or "binance_spot"))
        if not symbol:
            continue
        base = str(item.get("base") or "").strip().upper()
        quote = str(item.get("quote") or default_quote).strip().upper()
        normalized.append(
            {
                "symbol": symbol,
                "base": base or _infer_base(symbol, default_quote),
                "quote": quote,
                "exchange": str(item.get("exchange") or "binance_spot").strip().lower(),
                "asset_class": str(item.get("asset_class") or "crypto").strip().lower(),
                "enabled": bool(item.get("enabled", True)),
                "min_timeframe": str(item.get("min_timeframe") or "1m"),
                "strategy_enabled": bool(item.get("strategy_enabled", False)),
                "paper_enabled": bool(item.get("paper_enabled", True)),
                "live_enabled": bool(item.get("live_enabled", False)),
            }
        )
    strategy = payload.get("strategy") if isinstance(payload.get("strategy"), dict) else {}
    return {
        "version": payload.get("version"),
        "market": payload.get("market"),
        "default_quote_currency": default_quote,
        "strategy": dict(strategy),
        "symbols": normalized,
    }


def enabled_crypto_symbols(config_or_path: Any = None) -> list[str]:
    universe = _coerce_universe(config_or_path)
    return [item["symbol"] for item in universe if item.get("enabled")]


def is_crypto_symbol(symbol: str, config: Any = None) -> bool:
    normalized = normalize_crypto_symbol(symbol)
    if not normalized:
        return False
    universe = _coerce_universe(config)
    configured = {item["symbol"] for item in universe}
    if normalized in configured:
        return True

    base = _infer_base(normalized, "USDT")
    if base in KNOWN_CRYPTO_BASES:
        suffix = normalized[len(base) :]
        return suffix in {"USDT", "USD"} or normalized == base
    return False


def _coerce_universe(config_or_path: Any) -> list[dict[str, Any]]:
    if config_or_path is None:
        return load_crypto_universe()
    if isinstance(config_or_path, (str, Path)):
        return load_crypto_universe(config_or_path)
    if isinstance(config_or_path, dict):
        if isinstance(config_or_path.get("symbols"), list):
            payload_path = ROOT / ".tmp.crypto.universe.json"
            return _normalize_universe_payload(config_or_path)
        return _normalize_universe_payload({"symbols": config_or_path.get("crypto_universe", [])})
    if isinstance(config_or_path, list):
        return _normalize_universe_payload({"symbols": config_or_path})
    return []


def _normalize_universe_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    symbols = payload.get("symbols")
    if not isinstance(symbols, list):
        return []
    default_quote = str(payload.get("default_quote_currency") or "USDT").strip().upper() or "USDT"
    normalized: list[dict[str, Any]] = []
    for item in symbols:
        if not isinstance(item, dict):
            continue
        symbol = normalize_crypto_symbol(item.get("symbol", ""), exchange=str(item.get("exchange") or "binance_spot"))
        if not symbol:
            continue
        normalized.append(
            {
                "symbol": symbol,
                "base": str(item.get("base") or _infer_base(symbol, default_quote)).strip().upper(),
                "quote": str(item.get("quote") or default_quote).strip().upper(),
                "exchange": str(item.get("exchange") or "binance_spot").strip().lower(),
                "asset_class": str(item.get("asset_class") or "crypto").strip().lower(),
                "enabled": bool(item.get("enabled", True)),
                "min_timeframe": str(item.get("min_timeframe") or "1m"),
                "strategy_enabled": bool(item.get("strategy_enabled", False)),
                "paper_enabled": bool(item.get("paper_enabled", True)),
                "live_enabled": bool(item.get("live_enabled", False)),
            }
        )
    return normalized


def _infer_base(symbol: str, default_quote: str) -> str:
    upper = normalize_crypto_symbol(symbol)
    if upper.endswith(default_quote):
        return upper[: -len(default_quote)]
    if upper.endswith("USD"):
        return upper[:-3]
    return upper
