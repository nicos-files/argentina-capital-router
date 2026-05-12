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

    if plan.market_snapshot_id:
        completeness = ""
        snapshot_as_of = ""
        meta = dict(plan.metadata or {})
        snapshot_meta = meta.get("market_snapshot") or {}
        if isinstance(snapshot_meta, dict):
            completeness = str(snapshot_meta.get("completeness", "") or "")
            snapshot_as_of = str(snapshot_meta.get("as_of", "") or "")

        lines.append("## Market Snapshot")
        lines.append("")
        lines.append(f"- **Snapshot ID:** {plan.market_snapshot_id}")
        if snapshot_as_of:
            lines.append(f"- **As of:** {snapshot_as_of}")
        if completeness:
            lines.append(f"- **Completeness:** {completeness}")
        lines.append("")

        if plan.prices_used:
            lines.append("## Prices Used")
            lines.append("")
            lines.append("| Symbol | Asset class | Price | Currency | Provider | As of |")
            lines.append("| --- | --- | ---: | --- | --- | --- |")
            for quote in plan.prices_used:
                lines.append(
                    "| {symbol} | {asset_class} | {price:.2f} | {currency} | {provider} | {as_of} |".format(
                        symbol=quote.get("symbol", "?"),
                        asset_class=quote.get("asset_class", "?"),
                        price=float(quote.get("price", 0.0)),
                        currency=quote.get("currency", "?"),
                        provider=quote.get("provider", "?"),
                        as_of=quote.get("as_of", "?"),
                    )
                )
            lines.append("")

        if plan.fx_rates_used:
            lines.append("## FX Rates Used")
            lines.append("")
            lines.append("| Pair | Rate | As of | Provider | Delayed |")
            lines.append("| --- | ---: | --- | --- | --- |")
            for fx in plan.fx_rates_used:
                lines.append(
                    "| {pair} | {rate:.2f} | {as_of} | {provider} | {delayed} |".format(
                        pair=fx.get("pair", "?"),
                        rate=float(fx.get("rate", 0.0)),
                        as_of=fx.get("as_of", "?"),
                        provider=fx.get("provider", "?"),
                        delayed=bool(fx.get("delayed", True)),
                    )
                )
            lines.append("")

        if plan.rate_inputs_used:
            lines.append("## Rate Inputs Used")
            lines.append("")
            lines.append("| Key | Value | As of | Provider |")
            lines.append("| --- | ---: | --- | --- |")
            for rate in plan.rate_inputs_used:
                lines.append(
                    "| {key} | {value:.2f} | {as_of} | {provider} |".format(
                        key=rate.get("key", "?"),
                        value=float(rate.get("value", 0.0)),
                        as_of=rate.get("as_of", "?"),
                        provider=rate.get("provider", "?"),
                    )
                )
            lines.append("")

        if plan.data_warnings:
            lines.append("## Data Warnings")
            lines.append("")
            for warning in plan.data_warnings:
                lines.append(f"- {warning}")
            lines.append("")

    return "\n".join(lines).rstrip() + "\n"


__all__ = ["build_daily_report_markdown"]
