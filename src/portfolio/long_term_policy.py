"""Long-term policy loader and validation."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_POLICY_PATH = (
    _REPO_ROOT / "config" / "portfolio" / "long_term_policy.json"
)

_REQUIRED_ALLOC_KEYS = (
    "core_global_equity_pct",
    "cedears_single_names_pct",
    "argentina_equity_pct",
    "cash_or_short_term_yield_pct",
)
_REQUIRED_CONSTRAINT_KEYS = (
    "max_single_position_pct",
    "max_sector_pct",
    "min_trade_usd",
    "rebalance_threshold_pct",
    "cash_reserve_pct",
    "max_allocations_per_contribution",
)
_REQUIRED_RISK_BUCKETS = ("low", "medium", "high", "speculative")


@dataclass(frozen=True)
class LongTermPolicy:
    schema_version: str
    policy_id: str
    base_currency: str
    manual_review_only: bool
    live_trading_enabled: bool
    default_monthly_contribution_usd: float
    target_allocations: Mapping[str, float]
    constraints: Mapping[str, float]
    risk_buckets: Mapping[str, Mapping[str, float]]
    raw: Mapping[str, Any] = field(default_factory=dict)


def validate_long_term_policy(data: Mapping[str, Any]) -> None:
    if not isinstance(data, Mapping):
        raise ValueError("long-term policy must be an object")

    if data.get("manual_review_only") is not True:
        raise ValueError("manual_review_only must be true")
    if data.get("live_trading_enabled") is not False:
        raise ValueError("live_trading_enabled must be false")

    contribution = data.get("default_monthly_contribution_usd")
    try:
        contribution_val = float(contribution)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "default_monthly_contribution_usd must be numeric"
        ) from exc
    if contribution_val <= 0:
        raise ValueError("default_monthly_contribution_usd must be > 0")

    targets = data.get("target_allocations")
    if not isinstance(targets, Mapping):
        raise ValueError("target_allocations must be an object")
    for key in _REQUIRED_ALLOC_KEYS:
        if key not in targets:
            raise ValueError(f"target_allocations missing required key {key!r}")
    total_pct = sum(float(targets[k]) for k in _REQUIRED_ALLOC_KEYS)
    if abs(total_pct - 100.0) > 1e-6:
        raise ValueError(
            f"target_allocations must sum to 100, got {total_pct}"
        )

    constraints = data.get("constraints")
    if not isinstance(constraints, Mapping):
        raise ValueError("constraints must be an object")
    for key in _REQUIRED_CONSTRAINT_KEYS:
        if key not in constraints:
            raise ValueError(f"constraints missing required key {key!r}")
    if float(constraints["min_trade_usd"]) < 0:
        raise ValueError("constraints.min_trade_usd must be >= 0")
    if float(constraints["max_single_position_pct"]) <= 0:
        raise ValueError("constraints.max_single_position_pct must be > 0")
    try:
        max_allocs = int(constraints["max_allocations_per_contribution"])
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "constraints.max_allocations_per_contribution must be an integer"
        ) from exc
    if max_allocs <= 0:
        raise ValueError("constraints.max_allocations_per_contribution must be > 0")

    risk_buckets = data.get("risk_buckets")
    if not isinstance(risk_buckets, Mapping):
        raise ValueError("risk_buckets must be an object")
    for key in _REQUIRED_RISK_BUCKETS:
        if key not in risk_buckets:
            raise ValueError(f"risk_buckets missing required key {key!r}")
        if not isinstance(risk_buckets[key], Mapping):
            raise ValueError(f"risk_buckets.{key} must be an object")
        if "max_total_pct" not in risk_buckets[key]:
            raise ValueError(f"risk_buckets.{key} missing max_total_pct")


def load_long_term_policy(path: Path | str | None = None) -> LongTermPolicy:
    config_path = Path(path) if path is not None else _DEFAULT_POLICY_PATH
    if not config_path.exists():
        raise ValueError(f"long-term policy not found: {config_path}")
    try:
        with config_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{config_path}: invalid JSON: {exc}") from exc

    validate_long_term_policy(data)

    return LongTermPolicy(
        schema_version=str(data.get("schema_version", "")),
        policy_id=str(data.get("policy_id", "")),
        base_currency=str(data.get("base_currency", "USD")),
        manual_review_only=bool(data["manual_review_only"]),
        live_trading_enabled=bool(data["live_trading_enabled"]),
        default_monthly_contribution_usd=float(
            data["default_monthly_contribution_usd"]
        ),
        target_allocations={
            k: float(v) for k, v in data["target_allocations"].items()
        },
        constraints={k: float(v) for k, v in data["constraints"].items()},
        risk_buckets={
            k: {"max_total_pct": float(v["max_total_pct"])}
            for k, v in data["risk_buckets"].items()
        },
        raw=dict(data),
    )


__all__ = ["LongTermPolicy", "load_long_term_policy", "validate_long_term_policy"]
