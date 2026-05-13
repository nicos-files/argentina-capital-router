"""Telegram-friendly summary of a daily capital plan.

Manual review only. No live trading. No broker automation. No orders.

The formatter produces a short, plain-text message intended for the Telegram
``sendMessage`` API. Dynamic content (symbols, numbers) is kept free of
Markdown special characters so the message renders correctly whether or not
``parse_mode`` is set. The single Markdown character used in the header
(``*`` for bold the title) is applied only to literal strings under our
control, never to user-supplied or plan-derived strings.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Optional


_MAX_TELEGRAM_MESSAGE_LENGTH = 4096
_TRUNCATION_NOTICE = "\n... (truncated)"
# Markdown special chars that we strip from dynamic content. Underscore is
# deliberately not stripped: it is common in symbol-free strings such as
# decision names (e.g. ``INVEST_DIRECT_LONG_TERM``) and Telegram tolerates
# unmatched underscores without rejecting the message.
_FORBIDDEN_DYNAMIC_CHARS = ("*", "`", "[", "]")


def _strip_markdown(value: str) -> str:
    """Remove characters that would break a plain Markdown message.

    Dynamic content (symbols, rationales, warnings) is sanitized rather than
    escaped; this keeps the formatter simple and resilient when the chosen
    ``parse_mode`` differs from Markdown.
    """
    out = str(value)
    for ch in _FORBIDDEN_DYNAMIC_CHARS:
        out = out.replace(ch, "")
    return out.strip()


def _format_usd(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "0.00"


def load_daily_plan_for_telegram(plan_path: str | Path) -> dict:
    target = Path(plan_path)
    if not target.exists():
        raise ValueError(f"daily capital plan not found: {target}")
    try:
        with target.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{target}: invalid JSON: {exc}") from exc
    if not isinstance(data, Mapping):
        raise ValueError(f"{target}: plan must be a JSON object")
    return dict(data)


def load_execution_comparison_for_telegram(
    path: Optional[str | Path],
) -> Optional[dict]:
    if path is None:
        return None
    target = Path(path)
    if not target.exists():
        raise ValueError(f"execution comparison not found: {target}")
    try:
        with target.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{target}: invalid JSON: {exc}") from exc
    if not isinstance(data, Mapping):
        raise ValueError(f"{target}: comparison must be a JSON object")
    return dict(data)


def _truncate(text: str, limit: int = _MAX_TELEGRAM_MESSAGE_LENGTH) -> str:
    if len(text) <= limit:
        return text
    cutoff = max(0, limit - len(_TRUNCATION_NOTICE))
    return text[:cutoff] + _TRUNCATION_NOTICE


def format_daily_plan_telegram_message(
    plan: Mapping[str, Any],
    execution_comparison: Optional[Mapping[str, Any]] = None,
    max_allocations: int = 8,
) -> str:
    if max_allocations < 1:
        max_allocations = 1

    as_of = _strip_markdown(plan.get("as_of") or "unknown")
    decision = (plan.get("routing_decision") or {})
    decision_name = _strip_markdown(decision.get("decision") or "UNKNOWN")

    monthly = _format_usd(plan.get("monthly_long_term_contribution_usd"))
    portfolio_total = plan.get("portfolio_total_value_usd")
    allocations = list(plan.get("long_term_allocations") or [])
    skipped = list(plan.get("skipped_allocations") or [])
    warnings = list(plan.get("warnings") or [])
    allocation_warnings = list(plan.get("allocation_warnings") or [])

    lines: list[str] = []
    lines.append(f"Argentina Capital Router - {as_of}")
    lines.append("")
    lines.append(f"Decision: {decision_name}")
    lines.append("Manual review only. No live trading.")
    lines.append("")
    lines.append(f"Monthly contribution: USD {monthly}")
    if portfolio_total is not None:
        lines.append(f"Portfolio value: USD {_format_usd(portfolio_total)}")

    if allocations:
        lines.append("")
        lines.append("Recommended manual review allocation:")
        shown = allocations[:max_allocations]
        for index, allocation in enumerate(shown, start=1):
            symbol = _strip_markdown(allocation.get("symbol") or "?")
            amount = _format_usd(allocation.get("allocation_usd"))
            lines.append(f"{index}. {symbol} - USD {amount}")
        remainder = len(allocations) - len(shown)
        if remainder > 0:
            lines.append(f"... and {remainder} more")
    else:
        lines.append("")
        lines.append("Recommended manual review allocation: (none)")

    if skipped:
        lines.append("")
        lines.append(f"Skipped: {len(skipped)} below min trade")

    notice_lines: list[str] = []
    if allocation_warnings:
        notice_lines.append(
            f"Allocation warnings: {len(allocation_warnings)}"
        )
    if warnings:
        notice_lines.append(f"Warnings: {len(warnings)}")
        # Show the first warning so the user gets a hint of what is wrong.
        first = _strip_markdown(str(warnings[0]))
        if first:
            notice_lines.append(f"- {first}")
    if notice_lines:
        lines.append("")
        lines.extend(notice_lines)

    if execution_comparison is not None:
        lines.append("")
        lines.append("Execution comparison:")
        follow_rate = execution_comparison.get("follow_rate_pct")
        try:
            follow_str = f"{float(follow_rate):.1f}%"
        except (TypeError, ValueError):
            follow_str = "n/a"
        lines.append(f"Follow rate: {follow_str}")
        matched = execution_comparison.get("matched_symbols", 0)
        partial = execution_comparison.get("partial_symbols", 0)
        missed = execution_comparison.get("missed_symbols", 0)
        extra = execution_comparison.get("extra_symbols", 0)
        lines.append(
            f"Matched: {matched} | Partial: {partial} | "
            f"Missed: {missed} | Extra: {extra}"
        )

    text = "\n".join(lines).rstrip() + "\n"
    return _truncate(text)


__all__ = [
    "format_daily_plan_telegram_message",
    "load_daily_plan_for_telegram",
    "load_execution_comparison_for_telegram",
]
