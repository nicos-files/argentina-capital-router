"""Daily recommendation summary builder.

Manual review only. No live trading. No broker automation. No orders.

This module produces a small, stable JSON payload designed for downstream
consumers (Telegram bot, web UI, scheduled summary email) so they do not
have to walk the full ``DailyCapitalPlan`` to extract the few fields they
actually need.

The schema is intentionally minimal and deterministic:
  - manual_review_only / live_trading_enabled / no_orders flags are
    always present and always true / false / true respectively.
  - The summary never contains brokers, accounts, API keys, or orders.
  - Empty portfolios are explicitly flagged via ``is_empty_portfolio``.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from src.recommendations.models import DailyCapitalPlan


SCHEMA_VERSION = "1.0"
NOT_AN_ORDER_NOTE = (
    "These are not orders. Manual review required before placing any trade."
)


def is_empty_portfolio(plan: DailyCapitalPlan) -> bool:
    """Return True if the plan was built against an empty portfolio.

    Three signals, ordered from strongest to weakest:
      1. Portfolio metadata explicitly tagged ``source == "generated_empty"``
         (i.e. the ``--empty-portfolio`` flow).
      2. Portfolio summary shows zero positions and zero cash balances.
      3. No portfolio snapshot was passed at all.
    """
    if plan.portfolio_snapshot_id is None:
        return True
    meta = dict(plan.metadata or {})
    portfolio_meta = meta.get("portfolio_snapshot") or {}
    if isinstance(portfolio_meta, Mapping):
        if str(portfolio_meta.get("source", "")) == "generated_empty":
            return True
        summary = portfolio_meta.get("summary") or {}
        if isinstance(summary, Mapping):
            positions = int(summary.get("positions_loaded", 0) or 0)
            cash = int(summary.get("cash_balances_loaded", 0) or 0)
            if positions == 0 and cash == 0:
                return True
    return False


def _compact_allocation(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "symbol": str(raw.get("symbol", "")),
        "asset_class": str(raw.get("asset_class", "")),
        "bucket": str(raw.get("bucket", "")),
        "allocation_usd": float(raw.get("allocation_usd", 0.0) or 0.0),
        "rationale": str(raw.get("rationale", "") or ""),
    }


def _compact_skipped(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "symbol": str(raw.get("symbol", "")),
        "bucket": str(raw.get("bucket", "")),
        "suggested_usd": float(raw.get("suggested_usd", 0.0) or 0.0),
        "reason": str(raw.get("reason", "") or ""),
    }


def _data_quality_block(plan: DailyCapitalPlan) -> dict[str, Any]:
    meta = dict(plan.metadata or {})
    market_meta = meta.get("market_snapshot") or {}
    portfolio_meta = meta.get("portfolio_snapshot") or {}

    market_block = {
        "snapshot_id": plan.market_snapshot_id,
        "as_of": None,
        "source": None,
        "completeness": None,
    }
    if isinstance(market_meta, Mapping):
        market_block["as_of"] = market_meta.get("as_of")
        market_block["source"] = market_meta.get("source")
        market_block["completeness"] = market_meta.get("completeness")

    portfolio_block = {
        "snapshot_id": plan.portfolio_snapshot_id,
        "as_of": None,
        "source": None,
        "completeness": None,
        "positions_loaded": 0,
        "cash_balances_loaded": 0,
    }
    if isinstance(portfolio_meta, Mapping):
        portfolio_block["as_of"] = portfolio_meta.get("as_of")
        portfolio_block["source"] = portfolio_meta.get("source")
        portfolio_block["completeness"] = portfolio_meta.get("completeness")
        summary = portfolio_meta.get("summary") or {}
        if isinstance(summary, Mapping):
            portfolio_block["positions_loaded"] = int(
                summary.get("positions_loaded", 0) or 0
            )
            portfolio_block["cash_balances_loaded"] = int(
                summary.get("cash_balances_loaded", 0) or 0
            )

    return {
        "market_snapshot": market_block,
        "portfolio_snapshot": portfolio_block,
        "data_warnings": list(plan.data_warnings),
    }


def _tactical_block(plan: DailyCapitalPlan) -> dict[str, Any]:
    decision = dict(plan.routing_decision)
    meta = dict(plan.metadata or {})
    return {
        "tactical_capital_available_usd": float(
            meta.get("tactical_capital_available_usd", 0.0) or 0.0
        ),
        "tactical_capital_allocated_usd": float(
            decision.get("tactical_capital_allocated_usd", 0.0) or 0.0
        ),
        "opportunity_id": decision.get("opportunity_id"),
        "opportunity_simulated": bool(meta.get("opportunity_simulated", False)),
        "opportunity_from_snapshot": bool(
            meta.get("opportunity_from_snapshot", False)
        ),
    }


def _constraints_block(plan: DailyCapitalPlan) -> dict[str, Any]:
    meta = dict(plan.metadata or {})
    constraints = meta.get("constraints") or {}
    if isinstance(constraints, Mapping):
        return {
            "min_trade_usd": float(
                constraints.get("min_trade_usd", 0.0) or 0.0
            ),
            "max_allocations_per_contribution": int(
                constraints.get("max_allocations_per_contribution", 0) or 0
            ),
        }
    return {
        "min_trade_usd": 0.0,
        "max_allocations_per_contribution": 0,
    }


def _target_bucket_weights(plan: DailyCapitalPlan) -> dict[str, float]:
    meta = dict(plan.metadata or {})
    portfolio_meta = meta.get("portfolio_snapshot") or {}
    if not isinstance(portfolio_meta, Mapping):
        return {}
    targets = portfolio_meta.get("target_bucket_weights") or {}
    if not isinstance(targets, Mapping):
        return {}
    return {str(k): float(v) for k, v in targets.items()}


def build_daily_recommendation_summary(
    plan: DailyCapitalPlan,
    *,
    generated_files: Sequence[str] = (),
) -> dict[str, Any]:
    """Return a deterministic summary dict for downstream consumers.

    Parameters
    ----------
    plan : DailyCapitalPlan
        The plan to summarise. Must originate from the deterministic
        builder in ``run_daily_capital_plan`` so the policy / constraint
        metadata is populated.
    generated_files : Sequence[str]
        Basenames (or relative paths) of artifact files that were
        written to disk for the same run. The summary's own filename can
        be appended by the caller before / after building.
    """
    decision = dict(plan.routing_decision)
    is_empty = is_empty_portfolio(plan)

    # Combine plan-level warnings into a single de-duplicated list while
    # preserving order. allocation_warnings stay separate so a downstream
    # UI can render them with their own heading.
    seen: set[str] = set()
    merged_warnings: list[str] = []
    for source in (plan.warnings, plan.data_warnings):
        for w in source:
            text = str(w)
            if text and text not in seen:
                seen.add(text)
                merged_warnings.append(text)

    return {
        "schema_version": SCHEMA_VERSION,
        "manual_review_only": True,
        "live_trading_enabled": False,
        "no_orders": True,
        "date": plan.as_of,
        "recommendation_type": str(
            decision.get("decision", "") or ""
        ),
        "rationale": str(decision.get("rationale", "") or ""),
        "monthly_contribution_usd": float(
            plan.monthly_long_term_contribution_usd
        ),
        "is_empty_portfolio": bool(is_empty),
        "portfolio_total_value_usd": (
            float(plan.portfolio_total_value_usd)
            if plan.portfolio_total_value_usd is not None
            else None
        ),
        "current_bucket_weights": {
            str(k): float(v) for k, v in (plan.current_bucket_weights or {}).items()
        },
        "target_bucket_weights": _target_bucket_weights(plan),
        "recommended_allocations": [
            _compact_allocation(a) for a in plan.long_term_allocations
        ],
        "skipped_allocations": [
            _compact_skipped(s) for s in plan.skipped_allocations
        ],
        "unallocated_usd": float(plan.unallocated_usd),
        "warnings": merged_warnings,
        "allocation_warnings": list(plan.allocation_warnings),
        "portfolio_warnings": list(plan.portfolio_warnings),
        "constraints": _constraints_block(plan),
        "tactical": _tactical_block(plan),
        "data_quality": _data_quality_block(plan),
        "generated_files": list(generated_files),
        "note": NOT_AN_ORDER_NOTE,
    }


__all__ = [
    "SCHEMA_VERSION",
    "NOT_AN_ORDER_NOTE",
    "build_daily_recommendation_summary",
    "is_empty_portfolio",
]
