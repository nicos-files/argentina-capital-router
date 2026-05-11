from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


DEFAULT_CRYPTO_INTRADAY_STRATEGY_CONFIG = {
    "timeframe": "5m",
    "lookback_limit": 120,
    "fast_ma_window": 9,
    "slow_ma_window": 21,
    "min_abs_signal_strength": 0.001,
    "max_volatility_pct": 0.08,
    "min_volume_ratio": None,
    "risk_reward_ratio": 1.5,
    "stop_loss_pct": 0.006,
    "take_profit_pct": 0.009,
    "max_paper_notional": 25.0,
    "allow_short": False,
}


@dataclass(frozen=True)
class CryptoSignal:
    symbol: str
    action: str
    score: float
    confidence: float
    reason: str
    entry_price: float | None
    stop_loss: float | None
    take_profit: float | None
    max_notional: float | None
    risk_tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class IntradayCryptoBaselineStrategy:
    name = "intraday_crypto_baseline"

    def __init__(self, config: dict[str, Any] | None = None):
        merged = dict(DEFAULT_CRYPTO_INTRADAY_STRATEGY_CONFIG)
        merged.update(config or {})
        self.config = merged

    def evaluate(
        self,
        symbol: str,
        candles: pd.DataFrame,
        latest_quote: dict[str, Any] | None,
        provider_healthy: bool = True,
    ) -> CryptoSignal | None:
        if not provider_healthy:
            return None
        if candles is None or not isinstance(candles, pd.DataFrame) or candles.empty:
            return None

        frame = candles.copy()
        if "close" not in frame.columns:
            return None
        frame = frame.sort_values("date").reset_index(drop=True)
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce") if "volume" in frame.columns else 0.0
        frame = frame.dropna(subset=["close"])
        if frame.empty:
            return None

        slow_window = int(self.config["slow_ma_window"])
        fast_window = int(self.config["fast_ma_window"])
        if len(frame.index) < max(slow_window, fast_window) + 1:
            return None

        latest_price = self._extract_latest_price(latest_quote, frame)
        if latest_price is None or latest_price <= 0:
            return None

        fast_ma = float(frame["close"].rolling(window=fast_window).mean().iloc[-1])
        slow_ma = float(frame["close"].rolling(window=slow_window).mean().iloc[-1])
        if slow_ma <= 0:
            return None

        signal_strength = (fast_ma - slow_ma) / slow_ma
        if abs(signal_strength) < float(self.config["min_abs_signal_strength"]):
            return None

        returns = frame["close"].pct_change().dropna()
        if returns.empty:
            return None
        volatility_pct = float(returns.std(ddof=0) * (len(returns) ** 0.5))
        if volatility_pct > float(self.config["max_volatility_pct"]):
            return None

        recent_return = float((frame["close"].iloc[-1] / frame["close"].iloc[-2]) - 1.0)
        if fast_ma > slow_ma and recent_return > 0:
            stop_loss = latest_price * (1.0 - float(self.config["stop_loss_pct"]))
            take_profit = latest_price * (1.0 + float(self.config["take_profit_pct"]))
            confidence = min(1.0, max(signal_strength / max(float(self.config["min_abs_signal_strength"]), 1e-9), 0.0))
            return CryptoSignal(
                symbol=symbol,
                action="BUY",
                score=signal_strength,
                confidence=confidence,
                reason=(
                    f"fast_ma={fast_ma:.6f} > slow_ma={slow_ma:.6f}"
                    f" | recent_return={recent_return:.6f}"
                    f" | volatility_pct={volatility_pct:.6f}"
                ),
                entry_price=latest_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                max_notional=float(self.config["max_paper_notional"]),
                risk_tags=["trend_up", "momentum_positive"],
                metadata={
                    "fast_ma": fast_ma,
                    "slow_ma": slow_ma,
                    "signal_strength": signal_strength,
                    "recent_return": recent_return,
                    "volatility_pct": volatility_pct,
                    "timeframe": self.config["timeframe"],
                },
            )

        if fast_ma < slow_ma and bool(self.config.get("allow_short")):
            return None
        return None

    def _extract_latest_price(self, latest_quote: dict[str, Any] | None, candles: pd.DataFrame) -> float | None:
        if isinstance(latest_quote, dict):
            value = latest_quote.get("last_price")
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
        try:
            return float(candles["close"].iloc[-1])
        except (TypeError, ValueError, IndexError):
            return None
