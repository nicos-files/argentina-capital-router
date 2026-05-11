from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


EPSILON = 1e-12


def _serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value


@dataclass(frozen=True)
class CryptoPaperHistoryEntry:
    as_of: str
    date: str
    starting_equity: float
    ending_equity: float
    total_pnl: float
    total_return_pct: float
    realized_pnl: float
    unrealized_pnl: float
    fees_paid: float
    positions_value: float
    cash: float
    fills_count: int
    accepted_orders_count: int
    rejected_orders_count: int
    open_positions_count: int
    symbols_held: list[str]
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    paper_only: bool = True
    live_trading: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True)
class CryptoPaperEquityPoint:
    as_of: str
    equity: float
    cash: float
    positions_value: float
    cumulative_pnl: float
    cumulative_return_pct: float
    drawdown: float
    drawdown_pct: float
    daily_return_pct: float

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


@dataclass(frozen=True)
class CryptoPaperHistorySummary:
    start_date: str | None
    end_date: str | None
    days_count: int
    starting_equity: float
    ending_equity: float
    cumulative_pnl: float
    cumulative_return_pct: float
    best_day: dict[str, Any] | None
    worst_day: dict[str, Any] | None
    winning_days: int
    losing_days: int
    flat_days: int
    win_rate: float
    average_daily_return_pct: float
    volatility_daily_return_pct: float
    max_drawdown: float
    max_drawdown_pct: float
    total_fees_paid: float
    total_fills: int
    total_rejected_orders: int
    current_open_positions: int
    symbols_seen: list[str]
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    paper_only: bool = True
    live_trading: bool = False

    def to_dict(self) -> dict[str, Any]:
        return _serialize(asdict(self))


def load_crypto_paper_history(history_dir: str | Path) -> tuple[list[CryptoPaperHistoryEntry], list[str]]:
    root = Path(history_dir)
    path = root / "crypto_paper_performance_history.json"
    warnings: list[str] = []
    if not path.exists():
        warnings.append("Missing history artifact: crypto_paper_performance_history.json")
        return [], warnings
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        warnings.append(f"Malformed history artifact: {exc}")
        return [], warnings
    entries_payload = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries_payload, list):
        warnings.append("History artifact missing entries list.")
        return [], warnings
    entries = [_entry_from_payload(item) for item in entries_payload if isinstance(item, dict)]
    return [entry for entry in entries if entry is not None], warnings


def load_crypto_paper_daily_close_entry(daily_close_dir: str | Path) -> tuple[CryptoPaperHistoryEntry | None, list[str], dict[str, Any]]:
    root = Path(daily_close_dir)
    warnings: list[str] = []
    daily_close_path = root / "crypto_paper_daily_close.json"
    summary_path = root / "crypto_paper_performance_summary.json"
    if not daily_close_path.exists():
        warnings.append("Missing daily close artifact: crypto_paper_daily_close.json")
        return None, warnings, {}
    try:
        daily_close = json.loads(daily_close_path.read_text(encoding="utf-8"))
    except Exception as exc:
        warnings.append(f"Malformed daily close artifact: {exc}")
        return None, warnings, {}

    summary: dict[str, Any] = {}
    if summary_path.exists():
        try:
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                summary = payload
        except Exception as exc:
            warnings.append(f"Malformed performance summary artifact: {exc}")

    if not isinstance(daily_close, dict):
        warnings.append("Daily close artifact is not an object.")
        return None, warnings, {}

    performance = summary if summary else daily_close.get("performance")
    if not isinstance(performance, dict):
        warnings.append("Daily close artifact missing performance payload.")
        return None, warnings, {}

    positions_marked = daily_close.get("positions_marked")
    if not isinstance(positions_marked, list):
        positions_marked = []

    as_of = str(performance.get("as_of") or daily_close.get("as_of") or "").strip()
    date = as_of[:10] if len(as_of) >= 10 else str(daily_close.get("date") or "")
    entry = CryptoPaperHistoryEntry(
        as_of=as_of,
        date=date,
        starting_equity=float(performance.get("starting_equity") or 0.0),
        ending_equity=float(performance.get("ending_equity") or 0.0),
        total_pnl=float(performance.get("total_pnl") or 0.0),
        total_return_pct=float(performance.get("total_return_pct") or 0.0),
        realized_pnl=float(performance.get("realized_pnl") or 0.0),
        unrealized_pnl=float(performance.get("unrealized_pnl") or 0.0),
        fees_paid=float(performance.get("fees_paid") or 0.0),
        positions_value=float(performance.get("positions_value") or 0.0),
        cash=float(performance.get("ending_cash") or 0.0),
        fills_count=int(performance.get("fills_count") or 0),
        accepted_orders_count=int(performance.get("accepted_orders_count") or 0),
        rejected_orders_count=int(performance.get("rejected_orders_count") or 0),
        open_positions_count=int(performance.get("open_positions_count") or 0),
        symbols_held=sorted(str(symbol) for symbol in list(performance.get("symbols_held") or [])),
        warnings=list(daily_close.get("warnings") or performance.get("data_quality_warnings") or []),
        metadata={
            "positions_marked": positions_marked,
            "provider_health": daily_close.get("provider_health") or performance.get("provider_health") or {},
            "daily_close_artifacts_written": daily_close.get("artifacts_written") or {},
            "daily_close_metadata": daily_close.get("metadata") or {},
        },
        paper_only=bool(daily_close.get("paper_only", True) and performance.get("paper_only", True)),
        live_trading=bool(daily_close.get("live_trading", False) or performance.get("live_trading", False)),
    )
    return entry, warnings, daily_close


def upsert_crypto_paper_history(
    entries: list[CryptoPaperHistoryEntry],
    latest: CryptoPaperHistoryEntry | None,
) -> list[CryptoPaperHistoryEntry]:
    cleaned = [entry for entry in entries if entry is not None]
    if latest is None:
        return _sort_entries(cleaned)
    filtered = [entry for entry in cleaned if not _same_history_key(entry, latest)]
    filtered.append(latest)
    return _sort_entries(filtered)


def build_crypto_paper_equity_curve(entries: list[CryptoPaperHistoryEntry]) -> list[CryptoPaperEquityPoint]:
    ordered = _sort_entries(entries)
    if not ordered:
        return []
    first_starting_equity = float(ordered[0].starting_equity or 0.0)
    peak = -math.inf
    previous_equity: float | None = None
    points: list[CryptoPaperEquityPoint] = []
    for index, entry in enumerate(ordered):
        equity = float(entry.ending_equity or 0.0)
        peak = max(peak, equity)
        cumulative_pnl = equity - first_starting_equity
        cumulative_return_pct = ((cumulative_pnl / first_starting_equity) * 100.0) if abs(first_starting_equity) > EPSILON else 0.0
        drawdown = equity - peak
        drawdown_pct = ((drawdown / peak) * 100.0) if abs(peak) > EPSILON else 0.0
        if index == 0:
            base = float(entry.starting_equity or 0.0)
            daily_return_pct = ((equity - base) / base * 100.0) if abs(base) > EPSILON else 0.0
        else:
            daily_return_pct = ((equity - float(previous_equity or 0.0)) / float(previous_equity or 0.0) * 100.0) if abs(float(previous_equity or 0.0)) > EPSILON else 0.0
        points.append(
            CryptoPaperEquityPoint(
                as_of=entry.as_of,
                equity=equity,
                cash=float(entry.cash or 0.0),
                positions_value=float(entry.positions_value or 0.0),
                cumulative_pnl=cumulative_pnl,
                cumulative_return_pct=cumulative_return_pct,
                drawdown=drawdown,
                drawdown_pct=drawdown_pct,
                daily_return_pct=daily_return_pct,
            )
        )
        previous_equity = equity
    return points


def build_crypto_paper_drawdown_series(points: list[CryptoPaperEquityPoint]) -> list[dict[str, Any]]:
    return [
        {
            "as_of": point.as_of,
            "equity": point.equity,
            "drawdown": point.drawdown,
            "drawdown_pct": point.drawdown_pct,
        }
        for point in points
    ]


def build_crypto_paper_symbol_attribution(entries: list[CryptoPaperHistoryEntry]) -> tuple[list[dict[str, Any]], list[str]]:
    warnings = ["Limited symbol attribution: no realized per-symbol exit data available."]
    attribution: dict[str, dict[str, Any]] = {}
    for entry in _sort_entries(entries):
        positions = entry.metadata.get("positions_marked")
        if not isinstance(positions, list):
            continue
        for position in positions:
            if not isinstance(position, dict):
                continue
            symbol = str(position.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            current = attribution.setdefault(
                symbol,
                {
                    "symbol": symbol,
                    "latest_position_value": 0.0,
                    "latest_unrealized_pnl": 0.0,
                    "days_held_count": 0,
                    "appearances_count": 0,
                    "best_unrealized_pnl": None,
                    "worst_unrealized_pnl": None,
                    "last_seen_as_of": "",
                },
            )
            quantity = float(position.get("quantity") or 0.0)
            last_price = position.get("last_price")
            avg_entry = float(position.get("avg_entry_price") or 0.0)
            position_value = float(last_price if last_price is not None else avg_entry) * quantity
            unrealized = float(position.get("unrealized_pnl") or 0.0)
            current["appearances_count"] += 1
            if quantity > 0:
                current["days_held_count"] += 1
            if entry.as_of >= str(current["last_seen_as_of"]):
                current["last_seen_as_of"] = entry.as_of
                current["latest_position_value"] = position_value
                current["latest_unrealized_pnl"] = unrealized
            current["best_unrealized_pnl"] = unrealized if current["best_unrealized_pnl"] is None else max(current["best_unrealized_pnl"], unrealized)
            current["worst_unrealized_pnl"] = unrealized if current["worst_unrealized_pnl"] is None else min(current["worst_unrealized_pnl"], unrealized)
    items = [value for _, value in sorted(attribution.items())]
    return items, warnings


def build_crypto_paper_history_summary(
    entries: list[CryptoPaperHistoryEntry],
    points: list[CryptoPaperEquityPoint],
    symbol_attribution: list[dict[str, Any]],
    warnings: list[str] | None = None,
) -> CryptoPaperHistorySummary:
    ordered = _sort_entries(entries)
    warnings_list = list(warnings or [])
    if not ordered or not points:
        return CryptoPaperHistorySummary(
            start_date=None,
            end_date=None,
            days_count=0,
            starting_equity=0.0,
            ending_equity=0.0,
            cumulative_pnl=0.0,
            cumulative_return_pct=0.0,
            best_day=None,
            worst_day=None,
            winning_days=0,
            losing_days=0,
            flat_days=0,
            win_rate=0.0,
            average_daily_return_pct=0.0,
            volatility_daily_return_pct=0.0,
            max_drawdown=0.0,
            max_drawdown_pct=0.0,
            total_fees_paid=0.0,
            total_fills=0,
            total_rejected_orders=0,
            current_open_positions=0,
            symbols_seen=[],
            warnings=warnings_list,
            metadata={"paper_only": True, "live_trading": False},
        )

    daily_returns = [point.daily_return_pct for point in points]
    winning_days = sum(1 for value in daily_returns if value > EPSILON)
    losing_days = sum(1 for value in daily_returns if value < -EPSILON)
    flat_days = len(daily_returns) - winning_days - losing_days
    average_daily_return_pct = sum(daily_returns) / len(daily_returns)
    volatility_daily_return_pct = _stdev_population(daily_returns)
    max_drawdown = min(point.drawdown for point in points)
    max_drawdown_pct = min(point.drawdown_pct for point in points)
    symbols_seen = sorted({symbol for entry in ordered for symbol in entry.symbols_held})
    best_idx = max(range(len(points)), key=lambda idx: points[idx].daily_return_pct)
    worst_idx = min(range(len(points)), key=lambda idx: points[idx].daily_return_pct)
    best_day = _history_day_payload(ordered[best_idx], points[best_idx])
    worst_day = _history_day_payload(ordered[worst_idx], points[worst_idx])
    last_entry = ordered[-1]
    first_entry = ordered[0]
    last_point = points[-1]

    return CryptoPaperHistorySummary(
        start_date=first_entry.date,
        end_date=last_entry.date,
        days_count=len(ordered),
        starting_equity=float(first_entry.starting_equity or 0.0),
        ending_equity=float(last_entry.ending_equity or 0.0),
        cumulative_pnl=float(last_point.cumulative_pnl),
        cumulative_return_pct=float(last_point.cumulative_return_pct),
        best_day=best_day,
        worst_day=worst_day,
        winning_days=winning_days,
        losing_days=losing_days,
        flat_days=flat_days,
        win_rate=(winning_days / len(points)) if points else 0.0,
        average_daily_return_pct=average_daily_return_pct,
        volatility_daily_return_pct=volatility_daily_return_pct,
        max_drawdown=max_drawdown,
        max_drawdown_pct=max_drawdown_pct,
        total_fees_paid=sum(float(entry.fees_paid or 0.0) for entry in ordered),
        total_fills=sum(int(entry.fills_count or 0) for entry in ordered),
        total_rejected_orders=sum(int(entry.rejected_orders_count or 0) for entry in ordered),
        current_open_positions=int(last_entry.open_positions_count or 0),
        symbols_seen=symbols_seen,
        warnings=warnings_list,
        metadata={
            "paper_only": True,
            "live_trading": False,
            "symbol_attribution_count": len(symbol_attribution),
        },
    )


def write_crypto_paper_history_artifacts(
    history_dir: str | Path,
    entries: list[CryptoPaperHistoryEntry],
    points: list[CryptoPaperEquityPoint],
    summary: CryptoPaperHistorySummary,
    symbol_attribution: list[dict[str, Any]],
    attribution_warnings: list[str],
) -> dict[str, Path]:
    root = Path(history_dir)
    root.mkdir(parents=True, exist_ok=True)
    performance_history_payload = {
        "entries": [entry.to_dict() for entry in _sort_entries(entries)],
        "summary": summary.to_dict(),
        "paper_only": True,
        "live_trading": False,
    }
    payloads: dict[str, Any] = {
        "crypto_paper_performance_history.json": performance_history_payload,
        "crypto_paper_equity_curve.json": [point.to_dict() for point in points],
        "crypto_paper_drawdown_series.json": build_crypto_paper_drawdown_series(points),
        "crypto_paper_symbol_attribution.json": {
            "items": symbol_attribution,
            "warnings": attribution_warnings,
            "paper_only": True,
            "live_trading": False,
        },
    }
    written: dict[str, Path] = {}
    for filename, payload in payloads.items():
        path = root / filename
        path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
        written[filename] = path
    report_path = root / "crypto_paper_history_report.md"
    report_path.write_text(build_crypto_paper_history_report(entries, points, summary, symbol_attribution, attribution_warnings), encoding="utf-8")
    written[report_path.name] = report_path
    return written


def build_crypto_paper_history_report(
    entries: list[CryptoPaperHistoryEntry],
    points: list[CryptoPaperEquityPoint],
    summary: CryptoPaperHistorySummary,
    symbol_attribution: list[dict[str, Any]],
    attribution_warnings: list[str],
) -> str:
    lines = [
        "# Crypto Paper Performance History",
        "",
        "Paper-only analytics. No live orders were placed and no broker integration was used.",
        "",
        "## Summary",
        f"- Start date: {summary.start_date or 'n/a'}",
        f"- End date: {summary.end_date or 'n/a'}",
        f"- Days tracked: {summary.days_count}",
        f"- Starting equity: {summary.starting_equity:.6f}",
        f"- Ending equity: {summary.ending_equity:.6f}",
        f"- Cumulative P&L: {summary.cumulative_pnl:.6f}",
        f"- Cumulative return %: {summary.cumulative_return_pct:.6f}",
        f"- Max drawdown %: {summary.max_drawdown_pct:.6f}",
        f"- Win rate: {summary.win_rate * 100.0:.4f}",
        f"- Total fees paid: {summary.total_fees_paid:.6f}",
        f"- Total fills: {summary.total_fills}",
        "",
        "## Equity Curve",
    ]
    if not points:
        lines.append("- No equity points available.")
    else:
        latest = points[-1]
        best = max(points, key=lambda point: point.equity)
        worst = min(points, key=lambda point: point.equity)
        lines.extend(
            [
                f"- Latest equity: {latest.equity:.6f}",
                f"- Best equity: {best.equity:.6f}",
                f"- Worst equity: {worst.equity:.6f}",
                f"- Current drawdown: {latest.drawdown:.6f} ({latest.drawdown_pct:.6f}%)",
            ]
        )
    lines.extend(["", "## Daily Results"])
    if not entries or not points:
        lines.append("- No daily results available.")
    else:
        lines.append("| Date | Starting equity | Ending equity | Daily P&L | Daily return % | Fees | Fills | Rejected orders |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        ordered = _sort_entries(entries)
        for entry, point in zip(ordered, points):
            daily_pnl = float(entry.ending_equity) - float(entry.starting_equity)
            lines.append(
                f"| {entry.date} | {entry.starting_equity:.6f} | {entry.ending_equity:.6f} | "
                f"{daily_pnl:.6f} | {point.daily_return_pct:.6f} | {entry.fees_paid:.6f} | "
                f"{entry.fills_count} | {entry.rejected_orders_count} |"
            )
    lines.extend(["", "## Open Position Attribution"])
    if not symbol_attribution:
        lines.append("- No attribution available.")
    else:
        lines.append("| Symbol | Latest position value | Latest unrealized P&L | Appearances |")
        lines.append("| --- | ---: | ---: | ---: |")
        for item in symbol_attribution:
            lines.append(
                f"| {item['symbol']} | {float(item['latest_position_value']):.6f} | "
                f"{float(item['latest_unrealized_pnl']):.6f} | {int(item['appearances_count'])} |"
            )
    lines.extend(["", "## Warnings"])
    combined_warnings = list(summary.warnings) + list(attribution_warnings)
    if not combined_warnings:
        lines.append("- None.")
    else:
        for warning in combined_warnings:
            lines.append(f"- {warning}")
    lines.extend(
        [
            "",
            "## Notes",
            "- Paper-only.",
            "- No live orders placed.",
            "- No broker integration.",
            "- Realized P&L may be limited until SELL/EXIT simulation exists.",
        ]
    )
    return "\n".join(lines) + "\n"


def update_crypto_paper_history(
    *,
    daily_close_dir: str | Path,
    history_dir: str | Path,
) -> tuple[list[CryptoPaperHistoryEntry], list[CryptoPaperEquityPoint], CryptoPaperHistorySummary, list[dict[str, Any]], dict[str, Path], list[str]]:
    history_entries, history_warnings = load_crypto_paper_history(history_dir)
    latest_entry, daily_warnings, _ = load_crypto_paper_daily_close_entry(daily_close_dir)
    entries = upsert_crypto_paper_history(history_entries, latest_entry)
    points = build_crypto_paper_equity_curve(entries)
    symbol_attribution, attribution_warnings = build_crypto_paper_symbol_attribution(entries)
    summary = build_crypto_paper_history_summary(
        entries,
        points,
        symbol_attribution,
        warnings=history_warnings + daily_warnings + attribution_warnings,
    )
    artifacts = write_crypto_paper_history_artifacts(history_dir, entries, points, summary, symbol_attribution, attribution_warnings)
    return entries, points, summary, symbol_attribution, artifacts, history_warnings + daily_warnings + attribution_warnings


def _entry_from_payload(payload: dict[str, Any]) -> CryptoPaperHistoryEntry | None:
    try:
        return CryptoPaperHistoryEntry(
            as_of=str(payload.get("as_of") or ""),
            date=str(payload.get("date") or ""),
            starting_equity=float(payload.get("starting_equity") or 0.0),
            ending_equity=float(payload.get("ending_equity") or 0.0),
            total_pnl=float(payload.get("total_pnl") or 0.0),
            total_return_pct=float(payload.get("total_return_pct") or 0.0),
            realized_pnl=float(payload.get("realized_pnl") or 0.0),
            unrealized_pnl=float(payload.get("unrealized_pnl") or 0.0),
            fees_paid=float(payload.get("fees_paid") or 0.0),
            positions_value=float(payload.get("positions_value") or 0.0),
            cash=float(payload.get("cash") or 0.0),
            fills_count=int(payload.get("fills_count") or 0),
            accepted_orders_count=int(payload.get("accepted_orders_count") or 0),
            rejected_orders_count=int(payload.get("rejected_orders_count") or 0),
            open_positions_count=int(payload.get("open_positions_count") or 0),
            symbols_held=[str(item) for item in list(payload.get("symbols_held") or [])],
            warnings=list(payload.get("warnings") or []),
            metadata=dict(payload.get("metadata") or {}),
            paper_only=bool(payload.get("paper_only", True)),
            live_trading=bool(payload.get("live_trading", False)),
        )
    except Exception:
        return None


def _same_history_key(left: CryptoPaperHistoryEntry, right: CryptoPaperHistoryEntry) -> bool:
    if left.as_of and right.as_of:
        return left.as_of == right.as_of
    return left.date == right.date


def _sort_entries(entries: list[CryptoPaperHistoryEntry]) -> list[CryptoPaperHistoryEntry]:
    return sorted(entries, key=lambda entry: (entry.as_of or entry.date, entry.date))


def _history_day_payload(entry: CryptoPaperHistoryEntry, point: CryptoPaperEquityPoint) -> dict[str, Any]:
    return {
        "date": entry.date,
        "as_of": entry.as_of,
        "ending_equity": entry.ending_equity,
        "daily_return_pct": point.daily_return_pct,
        "total_pnl": entry.total_pnl,
    }


def _stdev_population(values: list[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return variance ** 0.5
