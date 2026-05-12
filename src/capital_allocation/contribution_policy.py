"""Contribution routing policy loader and validation."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_POLICY_PATH = (
    _REPO_ROOT / "config" / "capital_routing" / "contribution_policy.json"
)

_REQUIRED_THRESHOLDS = (
    "min_expected_net_return_pct",
    "min_score_to_route_capital",
    "max_fx_risk_score",
    "max_liquidity_risk_score",
)


@dataclass(frozen=True)
class ContributionRoutingPolicy:
    schema_version: str
    policy_id: str
    manual_review_only: bool
    live_trading_enabled: bool
    monthly_long_term_contribution_usd: float
    must_invest_long_term_by: str
    can_temporarily_use_contribution_for_tactical_opportunities: bool
    max_tactical_duration_days_for_contribution: int
    max_allowed_loss_pct_on_contribution: float
    loss_absorption_order: tuple
    tactical_bucket: Mapping[str, Any]
    opportunity_thresholds: Mapping[str, float]
    blocked_opportunity_types_for_contribution: tuple
    raw: Mapping[str, Any] = field(default_factory=dict)


def validate_contribution_policy(data: Mapping[str, Any]) -> None:
    if not isinstance(data, Mapping):
        raise ValueError("contribution policy must be an object")

    if data.get("manual_review_only") is not True:
        raise ValueError("manual_review_only must be true")
    if data.get("live_trading_enabled") is not False:
        raise ValueError("live_trading_enabled must be false")

    monthly = data.get("monthly_long_term_contribution_usd")
    try:
        monthly_val = float(monthly)
    except (TypeError, ValueError) as exc:
        raise ValueError("monthly_long_term_contribution_usd must be numeric") from exc
    if monthly_val <= 0:
        raise ValueError("monthly_long_term_contribution_usd must be > 0")

    max_dur = data.get("max_tactical_duration_days_for_contribution")
    try:
        max_dur_val = int(max_dur)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "max_tactical_duration_days_for_contribution must be an integer"
        ) from exc
    if max_dur_val < 0:
        raise ValueError("max_tactical_duration_days_for_contribution must be >= 0")

    max_loss = data.get("max_allowed_loss_pct_on_contribution")
    try:
        max_loss_val = float(max_loss)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "max_allowed_loss_pct_on_contribution must be numeric"
        ) from exc
    if max_loss_val < 0:
        raise ValueError("max_allowed_loss_pct_on_contribution must be >= 0")

    thresholds = data.get("opportunity_thresholds")
    if not isinstance(thresholds, Mapping):
        raise ValueError("opportunity_thresholds must be an object")
    for key in _REQUIRED_THRESHOLDS:
        if key not in thresholds:
            raise ValueError(f"opportunity_thresholds missing required key {key!r}")

    tactical = data.get("tactical_bucket")
    if not isinstance(tactical, Mapping):
        raise ValueError("tactical_bucket must be an object")

    blocked = data.get("blocked_opportunity_types_for_contribution")
    if not isinstance(blocked, list):
        raise ValueError("blocked_opportunity_types_for_contribution must be a list")


def load_contribution_policy(
    path: Path | str | None = None,
) -> ContributionRoutingPolicy:
    config_path = Path(path) if path is not None else _DEFAULT_POLICY_PATH
    if not config_path.exists():
        raise ValueError(f"contribution policy not found: {config_path}")
    try:
        with config_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{config_path}: invalid JSON: {exc}") from exc

    validate_contribution_policy(data)

    return ContributionRoutingPolicy(
        schema_version=str(data.get("schema_version", "")),
        policy_id=str(data.get("policy_id", "")),
        manual_review_only=bool(data["manual_review_only"]),
        live_trading_enabled=bool(data["live_trading_enabled"]),
        monthly_long_term_contribution_usd=float(
            data["monthly_long_term_contribution_usd"]
        ),
        must_invest_long_term_by=str(data.get("must_invest_long_term_by", "")),
        can_temporarily_use_contribution_for_tactical_opportunities=bool(
            data.get(
                "can_temporarily_use_contribution_for_tactical_opportunities", False
            )
        ),
        max_tactical_duration_days_for_contribution=int(
            data["max_tactical_duration_days_for_contribution"]
        ),
        max_allowed_loss_pct_on_contribution=float(
            data["max_allowed_loss_pct_on_contribution"]
        ),
        loss_absorption_order=tuple(data.get("loss_absorption_order", [])),
        tactical_bucket=dict(data["tactical_bucket"]),
        opportunity_thresholds={
            k: float(v) for k, v in data["opportunity_thresholds"].items()
        },
        blocked_opportunity_types_for_contribution=tuple(
            data["blocked_opportunity_types_for_contribution"]
        ),
        raw=dict(data),
    )


__all__ = [
    "ContributionRoutingPolicy",
    "load_contribution_policy",
    "validate_contribution_policy",
]
