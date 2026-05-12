"""CLI: build a daily capital plan for argentina-capital-router.

Manual review only. No network. No broker automation. No live trading. No API keys.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any, Optional

from src.capital_allocation.buckets import build_default_capital_state
from src.capital_allocation.capital_router import (
    INVEST_DIRECT_LONG_TERM,
    TacticalOpportunity,
    route_capital,
)
from src.capital_allocation.contribution_policy import load_contribution_policy
from src.market_data.ar_symbols import get_enabled_long_term_assets
from src.market_data.manual_snapshot import (
    ManualMarketSnapshot,
    load_manual_market_snapshot,
    summarize_snapshot,
)
from src.opportunities.carry_trade import (
    CarryInputs,
    build_carry_inputs_from_snapshot,
    score_carry_opportunity,
)
from src.portfolio.contribution_allocator import allocate_monthly_contribution
from src.portfolio.long_term_policy import load_long_term_policy
from src.recommendations.models import (
    CapitalPlanRecommendation,
    DailyCapitalPlan,
    LongTermContributionPlan,
)
from src.recommendations.writer import (
    dataclass_to_dict,
    write_json_artifact,
    write_markdown_report,
)
from src.reports.daily_report import build_daily_report_markdown


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_ARTIFACTS_DIR = _REPO_ROOT / "artifacts"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a daily capital plan (manual review only, no live trading)."
        )
    )
    parser.add_argument("--as-of", default=None, help="As-of date YYYY-MM-DD.")
    parser.add_argument(
        "--monthly-contribution-usd",
        type=float,
        default=None,
        help="Override monthly long-term contribution in USD.",
    )
    parser.add_argument(
        "--tactical-capital-usd",
        type=float,
        default=0.0,
        help="Optional tactical capital available (USD).",
    )
    parser.add_argument(
        "--simulate-carry",
        action="store_true",
        help="Simulate a carry-trade opportunity from CLI inputs.",
    )
    parser.add_argument("--carry-rate-pct", type=float, default=0.0)
    parser.add_argument("--carry-fx-devaluation-pct", type=float, default=0.0)
    parser.add_argument("--carry-cost-pct", type=float, default=0.0)
    parser.add_argument("--carry-duration-days", type=int, default=7)
    parser.add_argument("--carry-fx-risk-score", type=float, default=50.0)
    parser.add_argument("--carry-liquidity-risk-score", type=float, default=50.0)
    parser.add_argument(
        "--market-snapshot",
        type=Path,
        default=None,
        help=(
            "Optional path to a manual market snapshot JSON file. "
            "Read-only, no network."
        ),
    )
    parser.add_argument(
        "--carry-from-snapshot",
        action="store_true",
        help=(
            "Build carry-trade inputs from the snapshot rates. Requires "
            "--market-snapshot. Mutually exclusive with --simulate-carry."
        ),
    )
    parser.add_argument(
        "--carry-rate-key",
        type=str,
        default="money_market_monthly_pct",
        help="Snapshot rate key for expected monthly rate.",
    )
    parser.add_argument(
        "--carry-expected-fx-key",
        type=str,
        default="expected_fx_devaluation_monthly_pct",
        help="Snapshot rate key for expected FX devaluation (monthly pct).",
    )
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=_DEFAULT_ARTIFACTS_DIR,
        help="Where to write JSON/Markdown artifacts.",
    )
    return parser


def _build_carry_opportunity(args: argparse.Namespace) -> TacticalOpportunity:
    inputs = CarryInputs(
        opportunity_id="cli_simulated_carry",
        expected_monthly_rate_pct=float(args.carry_rate_pct),
        expected_fx_devaluation_pct=float(args.carry_fx_devaluation_pct),
        estimated_cost_pct=float(args.carry_cost_pct),
        duration_days=int(args.carry_duration_days),
        fx_risk_score=float(args.carry_fx_risk_score),
        liquidity_risk_score=float(args.carry_liquidity_risk_score),
        notes="CLI-simulated carry opportunity.",
    )
    return _carry_inputs_to_opportunity(inputs)


def _carry_inputs_to_opportunity(inputs: CarryInputs) -> TacticalOpportunity:
    carry_score = score_carry_opportunity(inputs)
    return TacticalOpportunity(
        opportunity_id=carry_score.opportunity_id,
        opportunity_type="carry_trade",
        expected_net_return_pct=carry_score.expected_net_return_pct,
        score=carry_score.score,
        duration_days=int(inputs.duration_days),
        fx_risk_score=float(inputs.fx_risk_score),
        liquidity_risk_score=float(inputs.liquidity_risk_score),
        uses_leverage=False,
        has_clear_exit_date=True,
        notes=f"classification={carry_score.classification}",
    )


def _build_carry_opportunity_from_snapshot(
    snapshot: ManualMarketSnapshot, args: argparse.Namespace
) -> TacticalOpportunity:
    inputs = build_carry_inputs_from_snapshot(
        snapshot,
        rate_key=str(args.carry_rate_key),
        expected_fx_key=str(args.carry_expected_fx_key),
        estimated_cost_pct=float(args.carry_cost_pct),
        duration_days=int(args.carry_duration_days),
        fx_risk_score=float(args.carry_fx_risk_score),
        liquidity_risk_score=float(args.carry_liquidity_risk_score),
        opportunity_id="snapshot_carry",
    )
    return _carry_inputs_to_opportunity(inputs)


def _validate_carry_source(args: argparse.Namespace) -> None:
    if args.simulate_carry and args.carry_from_snapshot:
        raise ValueError(
            "Use only one carry source: --simulate-carry or --carry-from-snapshot, not both."
        )
    if args.carry_from_snapshot and args.market_snapshot is None:
        raise ValueError("--carry-from-snapshot requires --market-snapshot PATH.")


def _snapshot_artifacts(snapshot: ManualMarketSnapshot) -> dict[str, Any]:
    prices_used = [dataclass_to_dict(q) for q in snapshot.quotes.values()]
    fx_rates_used = [dataclass_to_dict(fx) for fx in snapshot.fx_rates.values()]
    rate_inputs_used = [dataclass_to_dict(r) for r in snapshot.rates.values()]
    return {
        "prices_used": prices_used,
        "fx_rates_used": fx_rates_used,
        "rate_inputs_used": rate_inputs_used,
        "data_warnings": list(snapshot.warnings),
        "summary": summarize_snapshot(snapshot),
    }


def build_plan(args: argparse.Namespace) -> CapitalPlanRecommendation:
    _validate_carry_source(args)

    policy = load_contribution_policy()
    long_term_policy = load_long_term_policy()

    monthly = (
        float(args.monthly_contribution_usd)
        if args.monthly_contribution_usd is not None
        else float(policy.monthly_long_term_contribution_usd)
    )

    capital_state = build_default_capital_state(
        monthly_contribution_usd=monthly,
        tactical_capital_available_usd=float(args.tactical_capital_usd),
    )

    snapshot: Optional[ManualMarketSnapshot] = None
    snapshot_extras: dict[str, Any] = {}
    extra_warnings: list[str] = []
    if args.market_snapshot is not None:
        snapshot = load_manual_market_snapshot(args.market_snapshot)
        snapshot_extras = _snapshot_artifacts(snapshot)
        if snapshot.completeness == "partial":
            extra_warnings.append(
                f"Snapshot completeness is partial (snapshot_id={snapshot.snapshot_id})."
            )

    opportunity: Optional[TacticalOpportunity] = None
    if args.simulate_carry:
        opportunity = _build_carry_opportunity(args)
    elif args.carry_from_snapshot:
        assert snapshot is not None  # guaranteed by _validate_carry_source
        opportunity = _build_carry_opportunity_from_snapshot(snapshot, args)

    decision = route_capital(policy, capital_state, opportunity=opportunity)

    assets = get_enabled_long_term_assets()
    if decision.decision == INVEST_DIRECT_LONG_TERM:
        allocations = allocate_monthly_contribution(monthly, assets, long_term_policy)
    else:
        allocations = []

    as_of = args.as_of or date.today().isoformat()
    long_term_plan = LongTermContributionPlan(
        monthly_contribution_usd=monthly,
        allocations=[asdict(a) for a in allocations],
        base_currency=long_term_policy.base_currency,
        notes="Deterministic allocator, manual review only.",
    )

    metadata: dict[str, Any] = {
        "policy_id": policy.policy_id,
        "long_term_policy_id": long_term_policy.policy_id,
        "tactical_capital_available_usd": float(args.tactical_capital_usd),
        "universe_size": len(assets),
        "opportunity_simulated": bool(args.simulate_carry),
        "opportunity_from_snapshot": bool(args.carry_from_snapshot),
    }
    if snapshot is not None:
        metadata["market_snapshot"] = {
            "snapshot_id": snapshot.snapshot_id,
            "as_of": snapshot.as_of,
            "source": snapshot.source,
            "completeness": snapshot.completeness,
            "summary": snapshot_extras.get("summary", {}),
        }

    plan = DailyCapitalPlan(
        as_of=as_of,
        manual_review_only=True,
        live_trading_enabled=False,
        monthly_long_term_contribution_usd=monthly,
        routing_decision=dataclass_to_dict(decision),
        long_term_allocations=long_term_plan.allocations,
        warnings=tuple(list(decision.warnings) + extra_warnings),
        metadata=metadata,
        market_snapshot_id=(snapshot.snapshot_id if snapshot is not None else None),
        prices_used=tuple(snapshot_extras.get("prices_used", [])),
        fx_rates_used=tuple(snapshot_extras.get("fx_rates_used", [])),
        rate_inputs_used=tuple(snapshot_extras.get("rate_inputs_used", [])),
        data_warnings=tuple(snapshot_extras.get("data_warnings", [])),
    )
    return CapitalPlanRecommendation(plan=plan, long_term_plan=long_term_plan)


def _write_artifacts(
    artifacts_dir: Path, recommendation: CapitalPlanRecommendation
) -> dict[str, Path]:
    artifacts_dir = Path(artifacts_dir)
    capital_dir = artifacts_dir / "capital_routing"
    long_term_dir = artifacts_dir / "long_term"
    reports_dir = artifacts_dir / "reports"

    daily_capital_plan_path = capital_dir / "daily_capital_plan.json"
    contribution_plan_path = long_term_dir / "monthly_contribution_plan.json"
    report_path = reports_dir / "daily_report.md"

    write_json_artifact(daily_capital_plan_path, recommendation.plan)
    write_json_artifact(contribution_plan_path, recommendation.long_term_plan)

    report_markdown = build_daily_report_markdown(recommendation.plan)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_markdown, encoding="utf-8")

    return {
        "daily_capital_plan": daily_capital_plan_path,
        "monthly_contribution_plan": contribution_plan_path,
        "daily_report": report_path,
    }


def _print_summary(
    recommendation: CapitalPlanRecommendation, paths: dict[str, Path]
) -> None:
    plan = recommendation.plan
    decision = dict(plan.routing_decision)
    print("argentina-capital-router daily plan")
    print(f"  as_of: {plan.as_of}")
    print(f"  manual_review_only: {plan.manual_review_only}")
    print(f"  live_trading_enabled: {plan.live_trading_enabled}")
    print(f"  monthly_contribution_usd: {plan.monthly_long_term_contribution_usd:.2f}")
    print(f"  decision: {decision.get('decision')}")
    print(f"  rationale: {decision.get('rationale')}")
    print(f"  long_term_allocations: {len(plan.long_term_allocations)}")
    if plan.warnings:
        print("  warnings:")
        for w in plan.warnings:
            print(f"    - {w}")
    print("  artifacts:")
    for name, path in paths.items():
        print(f"    - {name}: {path}")


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    try:
        recommendation = build_plan(args)
    except ValueError as exc:
        print(f"error: {exc}")
        return 2
    paths = _write_artifacts(args.artifacts_dir, recommendation)
    _print_summary(recommendation, paths)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
