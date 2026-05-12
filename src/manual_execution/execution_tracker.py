"""Manual execution tracker and comparison against a daily capital plan.

Manual review only. No network. No broker. No live trading. No orders.

The tracker reads two local JSON files:

- A daily capital plan produced by :mod:`src.tools.run_daily_capital_plan`.
- A manual execution log filled in by a human after placing trades in their
  broker.

It then produces a deterministic comparison summary (matched / partial /
missed / extra symbols, follow rate, totals, fees) and writes a JSON artifact
plus a Markdown report. It never talks to a broker, never writes
``execution.plan`` or ``final_decision.json``, and never makes network calls.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from src.market_data.ar_symbols import normalize_ar_symbol
from src.recommendations.writer import (
    dataclass_to_dict,
    write_json_artifact,
    write_markdown_report,
)


MATCHED = "MATCHED"
PARTIAL = "PARTIAL"
MISSED = "MISSED"
EXTRA = "EXTRA"
_ALLOWED_STATUSES = {MATCHED, PARTIAL, MISSED, EXTRA}

_ALLOWED_SIDES = {"BUY", "SELL"}

_REQUIRED_LOG_FIELDS = (
    "schema_version",
    "execution_log_id",
    "as_of",
    "manual_review_only",
    "live_trading_enabled",
    "source",
    "broker",
    "base_currency",
    "executions",
)

_REQUIRED_EXEC_FIELDS = (
    "execution_id",
    "plan_id",
    "symbol",
    "asset_class",
    "side",
    "quantity",
    "price",
    "price_currency",
    "fees",
    "fees_currency",
    "executed_at",
    "broker",
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ManualExecution:
    execution_id: str
    plan_id: str
    symbol: str
    asset_class: str
    side: str
    quantity: float
    price: float
    price_currency: str
    fees: float
    fees_currency: str
    executed_at: str
    broker: str
    notes: str = ""


@dataclass(frozen=True)
class ManualExecutionLog:
    schema_version: str
    execution_log_id: str
    as_of: str
    manual_review_only: bool
    live_trading_enabled: bool
    source: str
    broker: str
    base_currency: str
    notes: str
    executions: tuple = field(default_factory=tuple)
    warnings: tuple = field(default_factory=tuple)
    completeness: str = "unknown"


@dataclass(frozen=True)
class PlanAllocation:
    symbol: str
    asset_class: str
    bucket: str
    recommended_usd: float
    rationale: str = ""


@dataclass(frozen=True)
class ExecutionComparisonItem:
    symbol: str
    asset_class: str
    recommended_usd: float
    executed_usd_estimate: float
    difference_usd: float
    status: str
    notes: str = ""


@dataclass(frozen=True)
class ExecutionComparisonSummary:
    plan_path: str
    execution_log_path: str
    as_of: str
    manual_review_only: bool
    live_trading_enabled: bool
    total_recommended_usd: float
    total_executed_usd_estimate: float
    total_fees_estimate: float
    matched_symbols: int
    partial_symbols: int
    missed_symbols: int
    extra_symbols: int
    follow_rate_pct: float
    items: tuple = field(default_factory=tuple)
    warnings: tuple = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def _coerce_float(value: Any, *, field_name: str, ctx: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{ctx}: {field_name} must be numeric") from exc


def _validate_log_top_level(data: Mapping[str, Any], path: Path) -> None:
    if not isinstance(data, Mapping):
        raise ValueError(f"{path}: execution log must be an object")
    for name in _REQUIRED_LOG_FIELDS:
        if name not in data:
            raise ValueError(f"{path}: missing top-level field {name!r}")
    if data.get("manual_review_only") is not True:
        raise ValueError(f"{path}: manual_review_only must be true")
    if data.get("live_trading_enabled") is not False:
        raise ValueError(f"{path}: live_trading_enabled must be false")
    if not isinstance(data.get("executions"), list):
        raise ValueError(f"{path}: executions must be a list")


def _parse_executions(
    items: Iterable[Mapping[str, Any]], path: Path
) -> tuple[ManualExecution, ...]:
    out: list[ManualExecution] = []
    for index, raw in enumerate(items):
        if not isinstance(raw, Mapping):
            raise ValueError(
                f"{path}: executions[{index}] must be an object"
            )
        for required in _REQUIRED_EXEC_FIELDS:
            if required not in raw:
                raise ValueError(
                    f"{path}: executions[{index}] missing required field {required!r}"
                )
        ctx = f"{path}: executions[{index}]"
        side = str(raw["side"]).strip().upper()
        if side not in _ALLOWED_SIDES:
            raise ValueError(
                f"{ctx}: side must be one of {sorted(_ALLOWED_SIDES)} (got {side!r})"
            )
        quantity = _coerce_float(raw["quantity"], field_name="quantity", ctx=ctx)
        if quantity <= 0:
            raise ValueError(f"{ctx}: quantity must be > 0 (got {quantity})")
        price = _coerce_float(raw["price"], field_name="price", ctx=ctx)
        if price <= 0:
            raise ValueError(f"{ctx}: price must be > 0 (got {price})")
        fees = _coerce_float(raw["fees"], field_name="fees", ctx=ctx)
        if fees < 0:
            raise ValueError(f"{ctx}: fees must be >= 0 (got {fees})")
        symbol = normalize_ar_symbol(str(raw["symbol"]))
        out.append(
            ManualExecution(
                execution_id=str(raw["execution_id"]),
                plan_id=str(raw["plan_id"]),
                symbol=symbol,
                asset_class=str(raw["asset_class"]),
                side=side,
                quantity=quantity,
                price=price,
                price_currency=str(raw["price_currency"]).strip().upper(),
                fees=fees,
                fees_currency=str(raw["fees_currency"]).strip().upper(),
                executed_at=str(raw["executed_at"]),
                broker=str(raw["broker"]),
                notes=str(raw.get("notes", "")),
            )
        )
    return tuple(out)


def _parse_quality(
    data: Mapping[str, Any], path: Path
) -> tuple[tuple[str, ...], str]:
    quality = data.get("quality")
    if quality is None:
        return tuple(), "unknown"
    if not isinstance(quality, Mapping):
        raise ValueError(f"{path}: quality must be an object if present")
    warnings_raw = quality.get("warnings", [])
    if warnings_raw is None:
        warnings: tuple[str, ...] = tuple()
    elif isinstance(warnings_raw, list):
        warnings = tuple(str(w) for w in warnings_raw)
    else:
        raise ValueError(f"{path}: quality.warnings must be a list when present")
    completeness = str(quality.get("completeness", "unknown")).strip().lower()
    return warnings, completeness


def load_manual_execution_log(path: str | Path) -> ManualExecutionLog:
    log_path = Path(path)
    if not log_path.exists():
        raise ValueError(f"manual execution log not found: {log_path}")
    try:
        with log_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{log_path}: invalid JSON: {exc}") from exc

    _validate_log_top_level(data, log_path)
    executions = _parse_executions(data["executions"], log_path)
    warnings, completeness = _parse_quality(data, log_path)

    return ManualExecutionLog(
        schema_version=str(data["schema_version"]),
        execution_log_id=str(data["execution_log_id"]),
        as_of=str(data["as_of"]),
        manual_review_only=True,
        live_trading_enabled=False,
        source=str(data["source"]),
        broker=str(data["broker"]),
        base_currency=str(data["base_currency"]).strip().upper() or "USD",
        notes=str(data.get("notes", "")),
        executions=executions,
        warnings=warnings,
        completeness=completeness,
    )


def load_plan_allocations(plan_path: str | Path) -> list[PlanAllocation]:
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

    if "manual_review_only" in data and data["manual_review_only"] is not True:
        raise ValueError(f"{target}: manual_review_only must be true if present")
    if (
        "live_trading_enabled" in data
        and data["live_trading_enabled"] is not False
    ):
        raise ValueError(
            f"{target}: live_trading_enabled must be false if present"
        )

    allocations_raw = data.get("long_term_allocations")
    if not isinstance(allocations_raw, list):
        raise ValueError(
            f"{target}: long_term_allocations must be a list"
        )

    out: list[PlanAllocation] = []
    for index, raw in enumerate(allocations_raw):
        if not isinstance(raw, Mapping):
            raise ValueError(
                f"{target}: long_term_allocations[{index}] must be an object"
            )
        for required in ("symbol", "asset_class", "bucket", "allocation_usd"):
            if required not in raw:
                raise ValueError(
                    f"{target}: long_term_allocations[{index}] missing field {required!r}"
                )
        symbol = normalize_ar_symbol(str(raw["symbol"]))
        recommended_usd = _coerce_float(
            raw["allocation_usd"],
            field_name="allocation_usd",
            ctx=f"{target}: long_term_allocations[{symbol!r}]",
        )
        if recommended_usd < 0:
            raise ValueError(
                f"{target}: long_term_allocations[{symbol!r}] allocation_usd must be >= 0"
            )
        out.append(
            PlanAllocation(
                symbol=symbol,
                asset_class=str(raw["asset_class"]),
                bucket=str(raw["bucket"]),
                recommended_usd=recommended_usd,
                rationale=str(raw.get("rationale", "")),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Estimation + comparison
# ---------------------------------------------------------------------------


def _resolve_usdars_rate(
    fx_rates: Optional[Mapping[str, float]],
    default_usdars_rate: Optional[float],
    key: str = "USDARS_MEP",
) -> Optional[float]:
    if fx_rates:
        candidate = fx_rates.get(key)
        if candidate is None:
            # also try a casing-insensitive lookup
            for stored_key, value in fx_rates.items():
                if str(stored_key).strip().upper() == key:
                    candidate = value
                    break
        if candidate is not None:
            try:
                rate = float(candidate)
            except (TypeError, ValueError):
                rate = 0.0
            if rate > 0:
                return rate
    if default_usdars_rate is not None:
        try:
            rate = float(default_usdars_rate)
        except (TypeError, ValueError):
            return None
        if rate > 0:
            return rate
    return None


def _convert_amount_to_usd(
    amount: float,
    currency: str,
    usdars_rate: Optional[float],
    *,
    label: str,
    symbol: str,
) -> tuple[float, list[str]]:
    """Return (usd_amount, warnings) for a given currency amount.

    For unrecognised currencies and ARS without an FX rate, the amount is
    returned as-is and a warning is appended; this keeps the tracker usable
    when no market snapshot is available, while making the imperfect
    conversion explicit.
    """
    currency_norm = (currency or "").strip().upper()
    if currency_norm == "USD":
        return float(amount), []
    if currency_norm == "ARS":
        if usdars_rate is None:
            return (
                float(amount),
                [
                    f"{label} for {symbol}: ARS amount treated as USD-equivalent "
                    "because no USDARS rate was provided."
                ],
            )
        return float(amount) / float(usdars_rate), []
    return (
        float(amount),
        [
            f"{label} for {symbol}: unsupported currency {currency_norm!r}; "
            "amount used as-is."
        ],
    )


def estimate_execution_usd(
    execution: ManualExecution,
    fx_rates: Optional[Mapping[str, float]] = None,
    default_usdars_rate: Optional[float] = None,
) -> tuple[float, float, list[str]]:
    """Estimate USD value and fees in USD for a single manual execution.

    Returns ``(executed_usd, fees_usd, warnings)``. Warnings collect any
    imperfect conversions (e.g. ARS treated as USD-equivalent because no FX
    rate is available).
    """
    usdars_rate = _resolve_usdars_rate(fx_rates, default_usdars_rate)
    warnings: list[str] = []

    notional_local = float(execution.price) * float(execution.quantity)
    executed_usd, w_notional = _convert_amount_to_usd(
        notional_local,
        execution.price_currency,
        usdars_rate,
        label="notional",
        symbol=execution.symbol,
    )
    warnings.extend(w_notional)

    fees_usd, w_fees = _convert_amount_to_usd(
        float(execution.fees),
        execution.fees_currency,
        usdars_rate,
        label="fees",
        symbol=execution.symbol,
    )
    warnings.extend(w_fees)

    return executed_usd, fees_usd, warnings


def _classify(
    recommended_usd: float, executed_usd: float
) -> str:
    if recommended_usd > 0 and executed_usd <= 0:
        return MISSED
    if recommended_usd <= 0 and executed_usd > 0:
        return EXTRA
    tolerance = max(1.0, 0.10 * recommended_usd)
    if abs(executed_usd - recommended_usd) <= tolerance:
        return MATCHED
    return PARTIAL


def compare_plan_to_manual_executions(
    plan_path: str | Path,
    execution_log_path: str | Path,
    default_usdars_rate: Optional[float] = None,
) -> ExecutionComparisonSummary:
    plan_path_obj = Path(plan_path)
    log_path_obj = Path(execution_log_path)

    allocations = load_plan_allocations(plan_path_obj)
    log = load_manual_execution_log(log_path_obj)

    aggregated: dict[str, dict[str, Any]] = {}
    warnings: list[str] = list(log.warnings)
    total_fees_usd = 0.0

    for execution in log.executions:
        if execution.side != "BUY":
            # Only BUY executions are compared against recommended allocations;
            # non-BUY sides are still totalled into fees and surfaced as a
            # warning so they remain visible without skewing the BUY-side
            # comparison.
            warnings.append(
                f"Execution {execution.execution_id} for {execution.symbol} "
                f"has side={execution.side!r}; excluded from BUY-side comparison."
            )
            _, fees_usd, w = estimate_execution_usd(
                execution, default_usdars_rate=default_usdars_rate
            )
            warnings.extend(w)
            total_fees_usd += fees_usd
            continue

        executed_usd, fees_usd, w = estimate_execution_usd(
            execution, default_usdars_rate=default_usdars_rate
        )
        warnings.extend(w)
        total_fees_usd += fees_usd

        bucket = aggregated.setdefault(
            execution.symbol,
            {
                "asset_class": execution.asset_class,
                "executed_usd": 0.0,
            },
        )
        bucket["executed_usd"] += executed_usd

    plan_lookup = {a.symbol: a for a in allocations}
    seen_symbols: set[str] = set()
    items: list[ExecutionComparisonItem] = []
    total_recommended_usd = 0.0
    total_executed_usd = 0.0

    # Plan symbols first (deterministic order: recommended desc, then symbol).
    sorted_plan = sorted(
        allocations,
        key=lambda a: (-float(a.recommended_usd), a.symbol),
    )
    for allocation in sorted_plan:
        executed_usd = float(
            aggregated.get(allocation.symbol, {}).get("executed_usd", 0.0)
        )
        status = _classify(allocation.recommended_usd, executed_usd)
        difference = executed_usd - allocation.recommended_usd
        items.append(
            ExecutionComparisonItem(
                symbol=allocation.symbol,
                asset_class=allocation.asset_class,
                recommended_usd=allocation.recommended_usd,
                executed_usd_estimate=executed_usd,
                difference_usd=difference,
                status=status,
                notes=allocation.rationale,
            )
        )
        total_recommended_usd += allocation.recommended_usd
        total_executed_usd += executed_usd
        seen_symbols.add(allocation.symbol)

    # EXTRA symbols (in executions but not in plan).
    extras = sorted(
        sym for sym in aggregated.keys() if sym not in seen_symbols
    )
    for sym in extras:
        bucket = aggregated[sym]
        executed_usd = float(bucket["executed_usd"])
        items.append(
            ExecutionComparisonItem(
                symbol=sym,
                asset_class=str(bucket["asset_class"]),
                recommended_usd=0.0,
                executed_usd_estimate=executed_usd,
                difference_usd=executed_usd,
                status=EXTRA,
                notes="Manual action not in the daily plan.",
            )
        )
        total_executed_usd += executed_usd

    matched = sum(1 for item in items if item.status == MATCHED)
    partial = sum(1 for item in items if item.status == PARTIAL)
    missed = sum(1 for item in items if item.status == MISSED)
    extra_count = sum(1 for item in items if item.status == EXTRA)

    recommended_symbol_count = len(plan_lookup)
    if recommended_symbol_count == 0:
        follow_rate_pct = 0.0
    else:
        follow_rate_pct = (
            (matched + partial) / recommended_symbol_count
        ) * 100.0

    # De-duplicate warnings preserving order.
    seen_w: set[str] = set()
    deduped: list[str] = []
    for w in warnings:
        if w not in seen_w:
            seen_w.add(w)
            deduped.append(w)

    return ExecutionComparisonSummary(
        plan_path=str(plan_path_obj),
        execution_log_path=str(log_path_obj),
        as_of=log.as_of,
        manual_review_only=True,
        live_trading_enabled=False,
        total_recommended_usd=total_recommended_usd,
        total_executed_usd_estimate=total_executed_usd,
        total_fees_estimate=total_fees_usd,
        matched_symbols=matched,
        partial_symbols=partial,
        missed_symbols=missed,
        extra_symbols=extra_count,
        follow_rate_pct=follow_rate_pct,
        items=tuple(items),
        warnings=tuple(deduped),
    )


# ---------------------------------------------------------------------------
# Report + artifact writers
# ---------------------------------------------------------------------------


def _format_usd(value: float) -> str:
    return f"{value:.2f}"


def build_manual_execution_report(
    summary: ExecutionComparisonSummary,
) -> str:
    lines: list[str] = []
    lines.append("# Manual Execution Tracker - Comparison Report")
    lines.append("")
    lines.append(f"**As of:** {summary.as_of}")
    lines.append("")
    lines.append(
        "> MANUAL REVIEW ONLY. No live trading. No broker automation. No orders placed."
    )
    lines.append("")
    lines.append("## Totals")
    lines.append("")
    lines.append(
        f"- **Total recommended USD:** {_format_usd(summary.total_recommended_usd)}"
    )
    lines.append(
        f"- **Total executed USD (estimate):** {_format_usd(summary.total_executed_usd_estimate)}"
    )
    lines.append(
        f"- **Total fees USD (estimate):** {_format_usd(summary.total_fees_estimate)}"
    )
    lines.append(f"- **Follow rate:** {summary.follow_rate_pct:.1f}%")
    lines.append(f"- **Matched symbols:** {summary.matched_symbols}")
    lines.append(f"- **Partial symbols:** {summary.partial_symbols}")
    lines.append(f"- **Missed symbols:** {summary.missed_symbols}")
    lines.append(f"- **Extra symbols:** {summary.extra_symbols}")
    lines.append("")
    lines.append("## Comparison by Symbol")
    lines.append("")
    lines.append(
        "| Symbol | Asset class | Recommended USD | Executed USD (est.) | Difference USD | Status |"
    )
    lines.append("| --- | --- | ---: | ---: | ---: | --- |")
    if not summary.items:
        lines.append("| _(no entries)_ | | | | | |")
    else:
        for item in summary.items:
            lines.append(
                "| {sym} | {ac} | {rec} | {ex} | {diff} | {st} |".format(
                    sym=item.symbol,
                    ac=item.asset_class,
                    rec=_format_usd(item.recommended_usd),
                    ex=_format_usd(item.executed_usd_estimate),
                    diff=_format_usd(item.difference_usd),
                    st=item.status,
                )
            )
    lines.append("")
    lines.append("## Sources")
    lines.append("")
    lines.append(f"- **Plan file:** `{summary.plan_path}`")
    lines.append(f"- **Execution log:** `{summary.execution_log_path}`")
    lines.append("")
    lines.append("## Warnings")
    lines.append("")
    if summary.warnings:
        for w in summary.warnings:
            lines.append(f"- {w}")
    else:
        lines.append("- _(no warnings)_")
    lines.append("")
    lines.append(
        "_Note: USD estimates may rely on a provided USDARS rate. When no rate "
        "was supplied, ARS amounts are treated as USD-equivalent; in that case "
        "the warnings above call this out explicitly._"
    )
    lines.append("")
    return "\n".join(lines)


def write_execution_comparison_artifacts(
    summary: ExecutionComparisonSummary,
    artifacts_dir: str | Path,
) -> dict[str, str]:
    base = Path(artifacts_dir) / "manual_execution"
    base.mkdir(parents=True, exist_ok=True)

    json_path = base / "manual_execution_comparison.json"
    write_json_artifact(json_path, summary)

    report_path = base / "manual_execution_report.md"
    report_path.write_text(
        build_manual_execution_report(summary), encoding="utf-8"
    )

    return {
        "manual_execution_comparison": str(json_path),
        "manual_execution_report": str(report_path),
    }


__all__ = [
    "MATCHED",
    "PARTIAL",
    "MISSED",
    "EXTRA",
    "ManualExecution",
    "ManualExecutionLog",
    "PlanAllocation",
    "ExecutionComparisonItem",
    "ExecutionComparisonSummary",
    "load_manual_execution_log",
    "load_plan_allocations",
    "estimate_execution_usd",
    "compare_plan_to_manual_executions",
    "build_manual_execution_report",
    "write_execution_comparison_artifacts",
]


# Re-export for callers that prefer the recommendations helper.
_ = dataclass_to_dict  # noqa: F401 - kept for downstream callers
_ = write_markdown_report  # noqa: F401 - reserved for future use
