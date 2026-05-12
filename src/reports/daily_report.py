"""Build a manual-review-only daily report from a DailyCapitalPlan."""
from __future__ import annotations

from src.recommendations.models import DailyCapitalPlan


def build_daily_report_markdown(plan: DailyCapitalPlan) -> str:
    lines: list[str] = []
    lines.append("# Argentina Capital Router - Daily Plan")
    lines.append("")
    lines.append(f"**As of:** {plan.as_of}")
    lines.append("")
    lines.append(
        "> MANUAL REVIEW ONLY. No live trading. No broker automation. No orders placed."
    )
    lines.append("")
    lines.append("## Routing")
    lines.append("")
    decision = dict(plan.routing_decision)
    lines.append(f"- **Decision:** {decision.get('decision', 'UNKNOWN')}")
    lines.append(
        f"- **Monthly long-term contribution USD:** {plan.monthly_long_term_contribution_usd:.2f}"
    )
    lines.append(
        f"- **Long-term allocated USD:** {float(decision.get('long_term_capital_allocated_usd', 0.0)):.2f}"
    )
    lines.append(
        f"- **Tactical allocated USD:** {float(decision.get('tactical_capital_allocated_usd', 0.0)):.2f}"
    )
    if decision.get("opportunity_id"):
        lines.append(f"- **Opportunity ID:** {decision['opportunity_id']}")
    rationale = decision.get("rationale")
    if rationale:
        lines.append("")
        lines.append(f"_Rationale:_ {rationale}")
    lines.append("")

    lines.append("## Long-term Allocation")
    lines.append("")
    if plan.long_term_allocations:
        lines.append("| Symbol | Asset class | Bucket | USD |")
        lines.append("| --- | --- | --- | ---: |")
        for alloc in plan.long_term_allocations:
            symbol = alloc.get("symbol", "?")
            asset_class = alloc.get("asset_class", "?")
            bucket = alloc.get("bucket", "?")
            usd = float(alloc.get("allocation_usd", 0.0))
            lines.append(f"| {symbol} | {asset_class} | {bucket} | {usd:.2f} |")
    else:
        lines.append("_No long-term allocations were produced (contribution routed elsewhere)._")
    lines.append("")

    lines.append("## Warnings")
    lines.append("")
    if plan.warnings:
        for warning in plan.warnings:
            lines.append(f"- {warning}")
    else:
        lines.append("_No warnings._")
    lines.append("")

    return "\n".join(lines).rstrip() + "\n"


__all__ = ["build_daily_report_markdown"]
