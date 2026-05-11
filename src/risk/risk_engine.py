from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


DEFAULT_RISK_CONFIG = {
    "min_data_quality_score": None,
    "min_expected_net_edge": None,
    "min_notional": None,
    "max_notional": None,
    "max_spread_pct": None,
    "reject_if_provider_unhealthy": True,
}


@dataclass
class RiskCheckInput:
    symbol: str
    side: str
    quantity: float | None = None
    notional: float | None = None
    price: float | None = None
    cash_available: float | None = None
    fees_estimate: float | None = None
    expected_net_edge: float | None = None
    spread_pct: float | None = None
    liquidity_score: float | None = None
    data_quality_score: float | None = None
    provider_healthy: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RiskCheckResult:
    approved: bool
    rejected_reason: str | None = None
    adjusted_quantity: float | None = None
    adjusted_notional: float | None = None
    risk_tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class RiskEngine:
    def __init__(self, config: dict[str, Any] | None = None):
        merged = dict(DEFAULT_RISK_CONFIG)
        merged.update(config or {})
        self.config = merged

    def evaluate(self, check: RiskCheckInput) -> RiskCheckResult:
        symbol = str(check.symbol or "").strip().upper()
        side = str(check.side or "").strip().upper()
        if not symbol:
            raise ValueError("symbol is required")
        if not side:
            raise ValueError("side is required")

        if self.config.get("reject_if_provider_unhealthy", True) and not check.provider_healthy:
            return self._reject("provider_unhealthy", "provider_unhealthy", check)

        minimum = self.config.get("min_data_quality_score")
        if minimum is not None and check.data_quality_score is not None and check.data_quality_score < float(minimum):
            return self._reject("data_quality_below_min", "data_quality", check)

        minimum = self.config.get("min_expected_net_edge")
        if minimum is not None and check.expected_net_edge is not None and check.expected_net_edge < float(minimum):
            return self._reject("expected_net_edge_below_min", "expected_net_edge", check)

        if (
            check.cash_available is not None
            and check.notional is not None
            and (float(check.notional) + float(check.fees_estimate or 0.0)) > float(check.cash_available) + 1e-9
        ):
            return self._reject("cash_insufficient", "cash", check)

        minimum = self.config.get("min_notional")
        if minimum is not None and check.notional is not None and float(check.notional) < float(minimum):
            return self._reject("notional_below_min", "min_notional", check)

        maximum = self.config.get("max_notional")
        if maximum is not None and check.notional is not None and float(check.notional) > float(maximum):
            return self._reject("notional_above_max", "max_notional", check)

        maximum = self.config.get("max_spread_pct")
        if maximum is not None and check.spread_pct is not None and float(check.spread_pct) > float(maximum):
            return self._reject("spread_above_max", "spread", check)

        return RiskCheckResult(
            approved=True,
            adjusted_quantity=check.quantity,
            adjusted_notional=check.notional,
            risk_tags=["approved"],
            metadata={"symbol": symbol, "side": side},
        )

    def _reject(self, reason: str, tag: str, check: RiskCheckInput) -> RiskCheckResult:
        return RiskCheckResult(
            approved=False,
            rejected_reason=reason,
            adjusted_quantity=check.quantity,
            adjusted_notional=check.notional,
            risk_tags=[tag, "rejected"],
            metadata={"symbol": str(check.symbol or "").strip().upper(), "side": str(check.side or "").strip().upper()},
        )
