"""Semantic reporting layer for crypto paper-forward artifacts.

Reads the canonical paper-forward artifacts produced by
``src.execution.crypto_paper_forward`` and turns them into a small set of
human-readable semantic events plus a one-page summary.

Paper-only / manual-review only. This module:

- never executes any trade;
- never contacts a broker, exchange or live API;
- never modifies the canonical artifacts it reads;
- never invents fills, orders, exits or P&L numbers;
- attaches ``paper_only=True`` and ``not_auto_executed=True`` to every event.

Public API:

- :func:`build_semantic_layer` — read artifacts and (optionally) write
  ``crypto_semantic_summary.json``, ``crypto_semantic_events.json`` and
  ``crypto_latest_action.md`` under ``<artifacts_dir>/semantic/``.
- :data:`SEMANTIC_EVENT_TYPES` and :data:`SEMANTIC_SEVERITIES` — public
  constants used by the Telegram notifier and dashboard.
- :data:`ALERTABLE_EVENT_TYPES` — the default set of event types eligible
  for alerts (NO_ACTION is intentionally excluded).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError  # Python 3.9+ stdlib
except ImportError:  # pragma: no cover - zoneinfo is stdlib in supported Python versions
    ZoneInfo = None  # type: ignore[assignment]

    class ZoneInfoNotFoundError(Exception):  # type: ignore[no-redef]
        pass

SEMANTIC_EVENT_TYPES: tuple[str, ...] = (
    "BUY_SIGNAL",
    "BUY_FILLED_PAPER",
    "SIGNAL_ONLY",
    "TAKE_PROFIT",
    "STOP_LOSS",
    "POSITION_OPEN",
    "ORDER_REJECTED",
    "DAILY_SUMMARY",
    "WARNING",
    "ERROR",
    "NO_ACTION",
)

SEMANTIC_SEVERITIES: tuple[str, ...] = ("INFO", "ACTION", "WARNING", "CRITICAL")

_SEVERITY_RANK: dict[str, int] = {name: idx for idx, name in enumerate(SEMANTIC_SEVERITIES)}

_DEFAULT_SEVERITY: dict[str, str] = {
    "BUY_SIGNAL": "INFO",
    "BUY_FILLED_PAPER": "ACTION",
    "SIGNAL_ONLY": "INFO",
    "TAKE_PROFIT": "ACTION",
    "STOP_LOSS": "ACTION",
    "POSITION_OPEN": "INFO",
    "ORDER_REJECTED": "WARNING",
    "DAILY_SUMMARY": "INFO",
    "WARNING": "WARNING",
    "ERROR": "CRITICAL",
    "NO_ACTION": "INFO",
}

ALERTABLE_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "BUY_FILLED_PAPER",
        "TAKE_PROFIT",
        "STOP_LOSS",
        "ORDER_REJECTED",
        "ERROR",
        "DAILY_SUMMARY",
    }
)

# SIGNAL_ONLY is intentionally excluded from ``ALERTABLE_EVENT_TYPES`` so the
# notifier does not surface it on Telegram by default. It is opt-in via
# ``--include-signal-only`` or env ``ENABLE_CRYPTO_SIGNAL_ONLY_ALERTS=1``.
SIGNAL_ONLY_EVENT_TYPE: str = "SIGNAL_ONLY"

CRYPTO_LOCAL_TZ_ENV: str = "CRYPTO_LOCAL_TZ"
DEFAULT_CRYPTO_LOCAL_TZ: str = "America/Argentina/Buenos_Aires"

# Curated tz abbreviations because zoneinfo's ``%Z`` often returns numeric
# offsets (e.g. ``-03``) for South-American zones. The notifier and dashboard
# fall back to ``%Z`` when the zone is not in this map.
_LOCAL_TZ_ABBREV: dict[str, str] = {
    "America/Argentina/Buenos_Aires": "ART",
    "America/Buenos_Aires": "ART",
    "America/New_York": "NYT",
    "America/Chicago": "CT",
    "America/Denver": "MT",
    "America/Los_Angeles": "PT",
    "America/Sao_Paulo": "BRT",
    "America/Mexico_City": "CST-MX",
    "Europe/Madrid": "CET",
    "Europe/London": "BST",
    "UTC": "UTC",
}

PAPER_DISCLAIMER = "Paper-only / manual-review only. Not auto-executed."

_SUMMARY_FILENAME = "crypto_semantic_summary.json"
_EVENTS_FILENAME = "crypto_semantic_events.json"
_LATEST_ACTION_FILENAME = "crypto_latest_action.md"


def build_semantic_layer(
    *,
    artifacts_dir: str | Path,
    output_dir: str | Path | None = None,
    write: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Read crypto paper artifacts and build semantic events + summary.

    Args:
        artifacts_dir: Root crypto paper artifacts directory (e.g.
            ``artifacts/crypto_paper``).
        output_dir: Where to write the three semantic artifacts. Defaults to
            ``<artifacts_dir>/semantic/``. Ignored when ``write`` is False.
        write: When True, persist the three semantic artifacts to disk.
        now: Optional clock override for ``created_at`` timestamps. Defaults
            to ``datetime.now(timezone.utc)``.

    Returns:
        ``{"summary": dict, "events": list[dict], "latest_action_md": str,
        "warnings": list[str], "output_paths": dict[str, str]}``.
    """

    root = Path(artifacts_dir)
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    moment_iso = moment.isoformat()

    snapshot = _load_json(root / "crypto_paper_snapshot.json", default={})
    positions = _load_json(root / "crypto_paper_positions.json", default=[])
    fills = _load_json(root / "crypto_paper_fills.json", default=[])
    orders = _load_json(root / "crypto_paper_orders.json", default=[])
    exit_events = _load_json(root / "crypto_paper_exit_events.json", default=[])
    metrics = _load_json(root / "evaluation" / "crypto_paper_strategy_metrics.json", default={})
    forward_result = _load_json(root / "paper_forward" / "crypto_paper_forward_result.json", default={})
    equity_curve = _load_json(root / "history" / "crypto_paper_equity_curve.json", default=[])
    manual_tickets = _load_json(root / "paper_forward" / "crypto_manual_trade_tickets.json", default=[])

    layer_warnings: list[str] = []
    if not isinstance(snapshot, dict):
        layer_warnings.append("snapshot_artifact_unreadable")
        snapshot = {}
    if not isinstance(positions, list):
        layer_warnings.append("positions_artifact_unreadable")
        positions = []
    if not isinstance(fills, list):
        layer_warnings.append("fills_artifact_unreadable")
        fills = []
    if not isinstance(orders, list):
        layer_warnings.append("orders_artifact_unreadable")
        orders = []
    if not isinstance(exit_events, list):
        layer_warnings.append("exit_events_artifact_unreadable")
        exit_events = []
    if not isinstance(metrics, dict):
        layer_warnings.append("metrics_artifact_unreadable")
        metrics = {}
    if not isinstance(forward_result, dict):
        layer_warnings.append("forward_result_artifact_unreadable")
        forward_result = {}
    if not isinstance(equity_curve, list):
        layer_warnings.append("equity_curve_artifact_unreadable")
        equity_curve = []
    if not isinstance(manual_tickets, list):
        layer_warnings.append("manual_tickets_artifact_unreadable")
        manual_tickets = []

    if not snapshot and not positions and not fills and not orders and not exit_events:
        layer_warnings.append(
            "no_paper_artifacts_found:expected files under "
            f"{root.as_posix()} (snapshot/positions/fills/orders/exit_events)"
        )

    metric_warnings = list(metrics.get("warnings") or []) if isinstance(metrics, dict) else []
    forward_warnings = list(forward_result.get("warnings") or []) if isinstance(forward_result, dict) else []

    closed_trades_count = int(metrics.get("closed_trades_count") or 0) if isinstance(metrics, dict) else 0
    if 0 < closed_trades_count < 30:
        layer_warnings.append(
            f"small_sample_size:closed_trades={closed_trades_count}_below_min_30"
        )

    events: list[dict[str, Any]] = []
    sources: list[str] = []

    sources.extend(
        _emit_buy_signal_events(orders=orders, created_at=moment_iso, events=events)
    )
    sources.extend(
        _emit_buy_filled_events(fills=fills, created_at=moment_iso, events=events)
    )
    sources.extend(
        _emit_signal_only_events(
            orders=orders,
            fills=fills,
            forward_result=forward_result,
            created_at=moment_iso,
            events=events,
        )
    )
    sources.extend(
        _emit_exit_events(
            exit_events=exit_events,
            fills=fills,
            created_at=moment_iso,
            events=events,
        )
    )
    sources.extend(
        _emit_position_open_events(positions=positions, created_at=moment_iso, events=events)
    )
    sources.extend(
        _emit_rejected_order_events(orders=orders, created_at=moment_iso, events=events)
    )
    sources.extend(
        _emit_warning_events(
            warnings=metric_warnings + forward_warnings + layer_warnings,
            created_at=moment_iso,
            events=events,
        )
    )
    sources.extend(
        _emit_error_events(forward_result=forward_result, created_at=moment_iso, events=events)
    )

    if not _has_actionable_event(events):
        events.append(_build_no_action_event(created_at=moment_iso))

    events.sort(
        key=lambda item: (
            -_SEVERITY_RANK.get(str(item.get("severity")), 0),
            str(item.get("created_at") or ""),
            str(item.get("event_id") or ""),
        ),
        reverse=False,
    )
    events.sort(
        key=lambda item: (
            _SEVERITY_RANK.get(str(item.get("severity")), 0),
            str(item.get("created_at") or ""),
        ),
        reverse=True,
    )

    # Resolve the local-display timezone (UTC archive ids are unchanged).
    local_tz_name = _resolve_local_tz_name()
    _enrich_events_with_local_display(events=events, tz_name=local_tz_name)

    summary = _build_summary(
        snapshot=snapshot,
        metrics=metrics,
        forward_result=forward_result,
        equity_curve=equity_curve,
        manual_tickets=manual_tickets,
        events=events,
        layer_warnings=layer_warnings,
        generated_at=moment_iso,
        local_tz_name=local_tz_name,
        artifacts_dir=root,
    )

    latest_action_md = _build_latest_action_markdown(summary=summary, events=events)

    output_paths: dict[str, str] = {}
    if write:
        target = Path(output_dir) if output_dir is not None else (root / "semantic")
        target.mkdir(parents=True, exist_ok=True)
        summary_path = target / _SUMMARY_FILENAME
        events_path = target / _EVENTS_FILENAME
        latest_action_path = target / _LATEST_ACTION_FILENAME
        summary_path.write_text(
            json.dumps(summary, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
            encoding="utf-8",
        )
        events_path.write_text(
            json.dumps(events, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
            encoding="utf-8",
        )
        latest_action_path.write_text(latest_action_md, encoding="utf-8")
        output_paths = {
            "summary": str(summary_path),
            "events": str(events_path),
            "latest_action": str(latest_action_path),
        }

    return {
        "summary": summary,
        "events": events,
        "latest_action_md": latest_action_md,
        "warnings": layer_warnings,
        "output_paths": output_paths,
    }


def _emit_buy_signal_events(
    *,
    orders: list[dict[str, Any]],
    created_at: str,
    events: list[dict[str, Any]],
) -> list[str]:
    sources: list[str] = []
    for order in orders:
        if not isinstance(order, dict):
            continue
        if str(order.get("side") or "").upper() != "BUY":
            continue
        order_id = str(order.get("order_id") or "")
        order_created = str(order.get("created_at") or "")
        events.append(
            _build_event(
                event_id=f"sig:{order_id}:{order_created}",
                event_type="BUY_SIGNAL",
                symbol=str(order.get("symbol") or ""),
                action="REVIEW",
                human_title=f"Crypto BUY signal {order.get('symbol')}",
                human_message=(
                    f"Strategy emitted BUY signal for {order.get('symbol')} at reference "
                    f"{_format_price(order.get('reference_price'))}. "
                    f"Status={order.get('status')}. {PAPER_DISCLAIMER}"
                ),
                manual_action="No action required. Signal recorded for manual review.",
                created_at=created_at,
                source_artifacts=["crypto_paper_orders.json"],
                metadata={
                    "order_id": order_id,
                    "status": order.get("status"),
                    "reference_price": order.get("reference_price"),
                    "requested_notional": order.get("requested_notional"),
                    "stop_loss": (order.get("metadata") or {}).get("stop_loss"),
                    "take_profit": (order.get("metadata") or {}).get("take_profit"),
                    "occurred_at": order_created,
                },
            )
        )
        sources.append("crypto_paper_orders.json")
    return sources


def _emit_buy_filled_events(
    *,
    fills: list[dict[str, Any]],
    created_at: str,
    events: list[dict[str, Any]],
) -> list[str]:
    sources: list[str] = []
    for fill in fills:
        if not isinstance(fill, dict):
            continue
        if str(fill.get("side") or "").upper() != "BUY":
            continue
        fill_id = str(fill.get("fill_id") or "")
        filled_at = str(fill.get("filled_at") or "")
        symbol = str(fill.get("symbol") or "")
        events.append(
            _build_event(
                event_id=f"buy:{fill_id}:{filled_at}",
                event_type="BUY_FILLED_PAPER",
                symbol=symbol,
                action="REVIEW_BUY",
                human_title=f"Paper BUY filled {symbol}",
                human_message=(
                    f"Paper BUY filled {fill.get('quantity')} @ "
                    f"{_format_price(fill.get('fill_price'))} "
                    f"(notional {_format_price(fill.get('gross_notional'))}). "
                    f"Stop {_format_price((fill.get('metadata') or {}).get('stop_loss'))} "
                    f"/ Take {_format_price((fill.get('metadata') or {}).get('take_profit'))}. "
                    f"{PAPER_DISCLAIMER}"
                ),
                manual_action=(
                    "Paper buy executed. Decide whether to mirror in your real account; "
                    "no auto-execution will occur."
                ),
                created_at=created_at,
                source_artifacts=["crypto_paper_fills.json"],
                metadata={
                    "fill_id": fill_id,
                    "order_id": fill.get("order_id"),
                    "quantity": fill.get("quantity"),
                    "fill_price": fill.get("fill_price"),
                    "gross_notional": fill.get("gross_notional"),
                    "fee": fill.get("fee"),
                    "stop_loss": (fill.get("metadata") or {}).get("stop_loss"),
                    "take_profit": (fill.get("metadata") or {}).get("take_profit"),
                    "quote_asset": _quote_asset_from_symbol(symbol),
                    "occurred_at": filled_at,
                },
            )
        )
        sources.append("crypto_paper_fills.json")
    return sources


def _emit_signal_only_events(
    *,
    orders: list[dict[str, Any]],
    fills: list[dict[str, Any]],
    forward_result: dict[str, Any],
    created_at: str,
    events: list[dict[str, Any]],
) -> list[str]:
    """Emit one ``SIGNAL_ONLY`` event per BUY order that did not produce a fill.

    A SIGNAL_ONLY event represents the case "the strategy detected a BUY
    opportunity, but paper execution did not open a position." Emission rule:

    - the artifact contains a BUY ``order`` (i.e. a paper-forward
      recommendation reached the order layer), AND
    - no entry in ``crypto_paper_fills.json`` carries a matching ``order_id``.

    The notifier may surface these events on Telegram only when the user
    explicitly opts in (``--include-signal-only`` /
    ``ENABLE_CRYPTO_SIGNAL_ONLY_ALERTS=1``). The semantic layer always records
    them so the dashboard and audit trail include unexecuted opportunities.
    """

    sources: list[str] = []
    if not isinstance(orders, list):
        return sources
    filled_order_ids: set[str] = set()
    if isinstance(fills, list):
        for fill in fills:
            if not isinstance(fill, dict):
                continue
            order_id = str(fill.get("order_id") or "").strip()
            if order_id:
                filled_order_ids.add(order_id)

    forward_meta = forward_result if isinstance(forward_result, dict) else {}
    rec_count = _safe_int(forward_meta.get("recommendations_count")) or 0
    fill_count = _safe_int(forward_meta.get("fills_count")) or 0

    for order in orders:
        if not isinstance(order, dict):
            continue
        if str(order.get("side") or "").upper() != "BUY":
            continue
        order_id = str(order.get("order_id") or "").strip()
        if not order_id:
            continue
        if order_id in filled_order_ids:
            # The recommendation actually opened a position; surfaced as
            # BUY_FILLED_PAPER instead.
            continue

        order_created = str(order.get("created_at") or "")
        symbol = str(order.get("symbol") or "")
        status = str(order.get("status") or "").upper()
        rejection_reason = order.get("reason")
        order_metadata = order.get("metadata") or {}
        events.append(
            _build_event(
                event_id=f"signal_only:{order_id}:{order_created}",
                event_type="SIGNAL_ONLY",
                symbol=symbol,
                action="REVIEW_SIGNAL",
                human_title=f"Crypto BUY signal not executed in paper: {symbol}",
                human_message=(
                    f"Strategy detected a BUY opportunity for {symbol} at "
                    f"{_format_price(order.get('reference_price'))} but paper "
                    f"execution did not open a position (status={status or 'UNKNOWN'}). "
                    f"{PAPER_DISCLAIMER}"
                ),
                manual_action=(
                    "Review the missed opportunity. No paper position was "
                    "opened; no live action will be taken."
                ),
                created_at=created_at,
                source_artifacts=[
                    "crypto_paper_orders.json",
                    "paper_forward/crypto_paper_forward_result.json",
                ],
                metadata={
                    "order_id": order_id,
                    "status": order.get("status"),
                    "reference_price": order.get("reference_price"),
                    "requested_notional": order.get("requested_notional"),
                    "stop_loss": order_metadata.get("stop_loss"),
                    "take_profit": order_metadata.get("take_profit"),
                    "rejection_reason": rejection_reason,
                    "reason": rejection_reason,
                    "quote_asset": _quote_asset_from_symbol(symbol),
                    "recommendations_count": rec_count,
                    "fills_count": fill_count,
                    "occurred_at": order_created,
                },
            )
        )
        sources.append("crypto_paper_orders.json")
    return sources


def _emit_exit_events(
    *,
    exit_events: list[dict[str, Any]],
    fills: list[dict[str, Any]],
    created_at: str,
    events: list[dict[str, Any]],
) -> list[str]:
    sources: list[str] = []
    for exit_event in exit_events:
        if not isinstance(exit_event, dict):
            continue
        reason = str(exit_event.get("exit_reason") or "").upper()
        if reason not in ("TAKE_PROFIT", "STOP_LOSS"):
            continue
        exit_id = str(exit_event.get("exit_id") or "")
        exited_at = str(exit_event.get("exited_at") or "")
        symbol = str(exit_event.get("symbol") or "")
        title = "Paper TAKE-PROFIT exit" if reason == "TAKE_PROFIT" else "Paper STOP-LOSS exit"
        manual = (
            "Paper take-profit closed. Consider closing your live position if you mirrored the entry."
            if reason == "TAKE_PROFIT"
            else "Paper stop-loss closed. Consider closing your live position if you mirrored the entry."
        )
        entry_average_price = _avg_buy_entry_price(
            fills=fills, symbol=symbol, before_iso=exited_at
        )
        return_pct = _return_pct(
            entry_price=entry_average_price,
            exit_price=exit_event.get("fill_price"),
        )
        events.append(
            _build_event(
                event_id=f"{reason.lower()}:{exit_id}:{exited_at}",
                event_type=reason,
                symbol=symbol,
                action="REVIEW_EXIT",
                human_title=f"{title}: {symbol}",
                human_message=(
                    f"{title} for {symbol} at "
                    f"{_format_price(exit_event.get('fill_price'))} "
                    f"(trigger {_format_price(exit_event.get('trigger_price'))}). "
                    f"Realized P&L {_format_price(exit_event.get('realized_pnl'))}. "
                    f"{PAPER_DISCLAIMER}"
                ),
                manual_action=manual,
                created_at=created_at,
                source_artifacts=["crypto_paper_exit_events.json"],
                metadata={
                    "exit_id": exit_id,
                    "exit_quantity": exit_event.get("exit_quantity"),
                    "trigger_price": exit_event.get("trigger_price"),
                    "fill_price": exit_event.get("fill_price"),
                    "realized_pnl": exit_event.get("realized_pnl"),
                    "fee": exit_event.get("fee"),
                    "source": exit_event.get("source"),
                    "stop_loss": (exit_event.get("metadata") or {}).get("stop_loss"),
                    "take_profit": (exit_event.get("metadata") or {}).get("take_profit"),
                    "entry_average_price": entry_average_price,
                    "return_pct": return_pct,
                    "quote_asset": _quote_asset_from_symbol(symbol),
                    "occurred_at": exited_at,
                },
            )
        )
        sources.append("crypto_paper_exit_events.json")
    return sources


def _emit_position_open_events(
    *,
    positions: list[dict[str, Any]],
    created_at: str,
    events: list[dict[str, Any]],
) -> list[str]:
    sources: list[str] = []
    for position in positions:
        if not isinstance(position, dict):
            continue
        try:
            quantity = float(position.get("quantity") or 0.0)
        except (TypeError, ValueError):
            continue
        if quantity <= 0.0:
            continue
        symbol = str(position.get("symbol") or "")
        updated_at = str(position.get("updated_at") or "")
        events.append(
            _build_event(
                event_id=f"pos:{symbol}:{updated_at}",
                event_type="POSITION_OPEN",
                symbol=symbol,
                action="MONITOR",
                human_title=f"Open paper position {symbol}",
                human_message=(
                    f"Open paper position {symbol} qty={quantity} avg "
                    f"{_format_price(position.get('avg_entry_price'))} last "
                    f"{_format_price(position.get('last_price'))} "
                    f"unrealized {_format_price(position.get('unrealized_pnl'))}. "
                    f"Stop {_format_price((position.get('metadata') or {}).get('stop_loss'))} "
                    f"/ Take {_format_price((position.get('metadata') or {}).get('take_profit'))}. "
                    f"{PAPER_DISCLAIMER}"
                ),
                manual_action="Monitor stop/take-profit levels. No action required while inside the band.",
                created_at=created_at,
                source_artifacts=["crypto_paper_positions.json"],
                metadata={
                    "quantity": quantity,
                    "avg_entry_price": position.get("avg_entry_price"),
                    "last_price": position.get("last_price"),
                    "unrealized_pnl": position.get("unrealized_pnl"),
                    "stop_loss": (position.get("metadata") or {}).get("stop_loss"),
                    "take_profit": (position.get("metadata") or {}).get("take_profit"),
                    "occurred_at": updated_at,
                },
            )
        )
        sources.append("crypto_paper_positions.json")
    return sources


def _emit_rejected_order_events(
    *,
    orders: list[dict[str, Any]],
    created_at: str,
    events: list[dict[str, Any]],
) -> list[str]:
    sources: list[str] = []
    for order in orders:
        if not isinstance(order, dict):
            continue
        if str(order.get("status") or "").upper() != "REJECTED":
            continue
        order_id = str(order.get("order_id") or "")
        order_created = str(order.get("created_at") or "")
        reason = order.get("reason") or "unspecified"
        events.append(
            _build_event(
                event_id=f"rej:{order_id}:{order_created}",
                event_type="ORDER_REJECTED",
                symbol=str(order.get("symbol") or ""),
                action="REVIEW_REJECTION",
                human_title=f"Paper order rejected {order.get('symbol')}",
                human_message=(
                    f"Paper order rejected for {order.get('symbol')} reason={reason} "
                    f"requested_notional={_format_price(order.get('requested_notional'))} "
                    f"reference_price={_format_price(order.get('reference_price'))}. "
                    f"{PAPER_DISCLAIMER}"
                ),
                manual_action=(
                    "Inspect rejection reason. No live action required; "
                    "fix configuration if reason is recurring."
                ),
                created_at=created_at,
                source_artifacts=["crypto_paper_orders.json"],
                metadata={
                    "order_id": order_id,
                    "reason": reason,
                    "reference_price": order.get("reference_price"),
                    "requested_notional": order.get("requested_notional"),
                    "occurred_at": order_created,
                },
            )
        )
        sources.append("crypto_paper_orders.json")
    return sources


def _emit_warning_events(
    *,
    warnings: Iterable[str],
    created_at: str,
    events: list[dict[str, Any]],
) -> list[str]:
    sources: list[str] = []
    seen: set[str] = set()
    for warning in warnings:
        if not warning:
            continue
        text = str(warning)
        if text in seen:
            continue
        seen.add(text)
        events.append(
            _build_event(
                event_id=f"warn:{text}",
                event_type="WARNING",
                symbol="",
                action="INVESTIGATE",
                human_title="Paper-forward warning",
                human_message=f"{text}. {PAPER_DISCLAIMER}",
                manual_action="Investigate; no live action required.",
                created_at=created_at,
                source_artifacts=[
                    "evaluation/crypto_paper_strategy_metrics.json",
                    "paper_forward/crypto_paper_forward_result.json",
                ],
                metadata={"raw_warning": text},
            )
        )
        sources.append("crypto_paper_strategy_metrics.json")
    return sources


def _emit_error_events(
    *,
    forward_result: dict[str, Any],
    created_at: str,
    events: list[dict[str, Any]],
) -> list[str]:
    sources: list[str] = []
    if not isinstance(forward_result, dict):
        return sources
    if str(forward_result.get("status") or "").upper() == "FAILED":
        events.append(
            _build_event(
                event_id=f"err:forward_status:{forward_result.get('status')}",
                event_type="ERROR",
                symbol="",
                action="INVESTIGATE",
                human_title="Crypto paper-forward run FAILED",
                human_message=(
                    "Last paper-forward run reported FAILED status. "
                    f"Validation errors: {forward_result.get('validation_errors') or []}. "
                    f"{PAPER_DISCLAIMER}"
                ),
                manual_action="Investigate validation errors before retrying.",
                created_at=created_at,
                source_artifacts=["paper_forward/crypto_paper_forward_result.json"],
                metadata={
                    "status": forward_result.get("status"),
                    "validation_errors": forward_result.get("validation_errors"),
                },
            )
        )
        sources.append("crypto_paper_forward_result.json")
    step_status = forward_result.get("step_status") or {}
    if isinstance(step_status, dict):
        for step, status in sorted(step_status.items()):
            if str(status or "").upper() == "FAILED":
                events.append(
                    _build_event(
                        event_id=f"err:step:{step}",
                        event_type="ERROR",
                        symbol="",
                        action="INVESTIGATE",
                        human_title=f"Paper-forward step FAILED: {step}",
                        human_message=(
                            f"Step '{step}' reported FAILED in last paper-forward run. "
                            f"{PAPER_DISCLAIMER}"
                        ),
                        manual_action="Investigate step logs; no live action required.",
                        created_at=created_at,
                        source_artifacts=["paper_forward/crypto_paper_forward_result.json"],
                        metadata={"step": step, "status": status},
                    )
                )
                sources.append("crypto_paper_forward_result.json")
    return sources


def _has_actionable_event(events: list[dict[str, Any]]) -> bool:
    for event in events:
        event_type = str(event.get("event_type") or "")
        if event_type in (
            "BUY_FILLED_PAPER",
            "TAKE_PROFIT",
            "STOP_LOSS",
            "POSITION_OPEN",
            "ORDER_REJECTED",
            "ERROR",
            "BUY_SIGNAL",
            "SIGNAL_ONLY",
        ):
            return True
    return False


def _build_no_action_event(*, created_at: str) -> dict[str, Any]:
    return _build_event(
        event_id="noop:latest",
        event_type="NO_ACTION",
        symbol="",
        action="NONE",
        human_title="No action required",
        human_message=(
            "No fresh fills, exits, rejections or warnings detected in the latest "
            f"paper-forward run. {PAPER_DISCLAIMER}"
        ),
        manual_action="No action required.",
        created_at=created_at,
        source_artifacts=[],
        metadata={},
    )


def _build_event(
    *,
    event_id: str,
    event_type: str,
    symbol: str,
    action: str,
    human_title: str,
    human_message: str,
    manual_action: str,
    created_at: str,
    source_artifacts: list[str],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    if event_type not in SEMANTIC_EVENT_TYPES:
        raise ValueError(f"Unknown semantic event_type: {event_type!r}")
    severity = _DEFAULT_SEVERITY[event_type]
    return {
        "event_id": event_id,
        "event_type": event_type,
        "severity": severity,
        "symbol": symbol,
        "action": action,
        "human_title": human_title,
        "human_message": human_message,
        "manual_action": manual_action,
        "paper_only": True,
        "not_auto_executed": True,
        "created_at": created_at,
        "source_artifacts": list(source_artifacts),
        "metadata": dict(metadata),
    }


def _build_summary(
    *,
    snapshot: dict[str, Any],
    metrics: dict[str, Any],
    forward_result: dict[str, Any],
    equity_curve: list[dict[str, Any]],
    manual_tickets: list[dict[str, Any]],
    events: list[dict[str, Any]],
    layer_warnings: list[str],
    generated_at: str,
    local_tz_name: str,
    artifacts_dir: Path,
) -> dict[str, Any]:
    starting_equity = _starting_equity_from_curve(equity_curve)
    current_equity = _safe_float(snapshot.get("equity"))
    total_return_pct: float | None = None
    if starting_equity and current_equity is not None and starting_equity != 0:
        total_return_pct = ((current_equity - starting_equity) / starting_equity) * 100.0
    counts_by_type: dict[str, int] = {name: 0 for name in SEMANTIC_EVENT_TYPES}
    for event in events:
        event_type = str(event.get("event_type") or "")
        counts_by_type[event_type] = counts_by_type.get(event_type, 0) + 1
    latest_event = events[0] if events else None
    summary = {
        "generated_at": generated_at,
        "paper_only": True,
        "not_auto_executed": True,
        "live_trading": False,
        "disclaimer": PAPER_DISCLAIMER,
        "artifacts_dir": str(artifacts_dir),
        "snapshot": {
            "as_of": snapshot.get("as_of"),
            "equity": current_equity,
            "cash": _safe_float(snapshot.get("cash")),
            "positions_value": _safe_float(snapshot.get("positions_value")),
            "realized_pnl": _safe_float(snapshot.get("realized_pnl")),
            "unrealized_pnl": _safe_float(snapshot.get("unrealized_pnl")),
            "fees_paid": _safe_float(snapshot.get("fees_paid")),
            "open_positions_count": len(snapshot.get("positions") or []),
        },
        "performance": {
            "starting_equity": starting_equity,
            "total_return_pct": total_return_pct,
            "closed_trades_count": _safe_int(metrics.get("closed_trades_count")),
            "open_trades_count": _safe_int(metrics.get("open_trades_count")),
            "win_rate": _safe_float(metrics.get("win_rate")),
            "expectancy": _safe_float(metrics.get("expectancy")),
            "profit_factor": _safe_float(metrics.get("profit_factor")),
            "net_profit": _safe_float(metrics.get("net_profit")),
            "total_fees": _safe_float(metrics.get("total_fees")),
            "total_slippage": _safe_float(metrics.get("total_slippage")),
            "stop_loss_count": _safe_int(metrics.get("stop_loss_count")),
            "take_profit_count": _safe_int(metrics.get("take_profit_count")),
        },
        "rejected_orders_count": counts_by_type.get("ORDER_REJECTED", 0),
        "signal_only_count": counts_by_type.get("SIGNAL_ONLY", 0),
        "manual_tickets_count": len(manual_tickets),
        "events_count_by_type": counts_by_type,
        "events_total": len(events),
        "latest_event": latest_event,
        "local_tz": local_tz_name,
        "generated_at_local": _local_display_for(generated_at, tz_name=local_tz_name),
        "warnings": list(layer_warnings) + list(metrics.get("warnings") or []) + list(forward_result.get("warnings") or []),
        "forward_run_status": forward_result.get("status"),
    }
    return summary


def _build_latest_action_markdown(*, summary: dict[str, Any], events: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    lines.append("# Crypto Paper Latest Action")
    lines.append("")
    lines.append(f"**Status:** {PAPER_DISCLAIMER}")
    lines.append("")
    snapshot = summary.get("snapshot") or {}
    performance = summary.get("performance") or {}
    lines.append("## Snapshot")
    lines.append(f"- As of: {snapshot.get('as_of') or 'n/a'}")
    lines.append(f"- Equity: {_format_price(snapshot.get('equity'))}")
    lines.append(f"- Cash: {_format_price(snapshot.get('cash'))}")
    lines.append(f"- Realized P&L: {_format_price(snapshot.get('realized_pnl'))}")
    lines.append(f"- Unrealized P&L: {_format_price(snapshot.get('unrealized_pnl'))}")
    lines.append(f"- Open positions: {snapshot.get('open_positions_count', 0)}")
    lines.append("")
    lines.append("## Performance")
    lines.append(f"- Closed trades: {performance.get('closed_trades_count')}")
    lines.append(f"- Win rate: {_format_pct(performance.get('win_rate'))}")
    lines.append(f"- Expectancy: {_format_price(performance.get('expectancy'))}")
    lines.append(f"- Net profit: {_format_price(performance.get('net_profit'))}")
    lines.append(f"- Take-profits: {performance.get('take_profit_count')}")
    lines.append(f"- Stop-losses: {performance.get('stop_loss_count')}")
    lines.append("")
    latest_event = summary.get("latest_event")
    lines.append("## Latest event")
    if latest_event:
        lines.append(f"- Type: {latest_event.get('event_type')}")
        lines.append(f"- Severity: {latest_event.get('severity')}")
        if latest_event.get("symbol"):
            lines.append(f"- Symbol: {latest_event.get('symbol')}")
        lines.append(f"- Title: {latest_event.get('human_title')}")
        lines.append(f"- Message: {latest_event.get('human_message')}")
        lines.append(f"- Manual action: {latest_event.get('manual_action')}")
    else:
        lines.append("- (none)")
    lines.append("")
    warnings = summary.get("warnings") or []
    if warnings:
        lines.append("## Warnings")
        for warning in warnings:
            lines.append(f"- {warning}")
        lines.append("")
    lines.append("## Disclaimers")
    lines.append("- Paper-only. No live execution occurred.")
    lines.append("- Fees and slippage are simulated.")
    lines.append("- Manual review required before mirroring in any live account.")
    lines.append("")
    return "\n".join(lines)


def _starting_equity_from_curve(equity_curve: list[dict[str, Any]]) -> float | None:
    for point in equity_curve:
        if not isinstance(point, dict):
            continue
        value = _safe_float(point.get("equity"))
        if value is not None:
            return value
    return None


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _format_price(value: Any) -> str:
    parsed = _safe_float(value)
    if parsed is None:
        return "n/a"
    return f"{parsed:,.6f}".rstrip("0").rstrip(".")


_QUOTE_ASSET_SUFFIXES: tuple[str, ...] = (
    "USDT", "USDC", "BUSD", "FDUSD", "TUSD", "DAI", "USD", "EUR", "BTC", "ETH", "BNB",
)


def _quote_asset_from_symbol(symbol: str) -> str | None:
    """Best-effort quote-asset extraction for Binance-style spot symbols.

    Returns ``None`` when the symbol does not match any known suffix; callers
    must therefore tolerate ``None`` and fall back to a generic label.
    """

    text = str(symbol or "").upper().strip()
    if not text:
        return None
    for suffix in _QUOTE_ASSET_SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix):
            return suffix
    return None


def _avg_buy_entry_price(
    *,
    fills: list[dict[str, Any]],
    symbol: str,
    before_iso: str,
) -> float | None:
    """Quantity-weighted average BUY fill price for ``symbol`` up to ``before_iso``.

    Returns ``None`` when no BUY fill is found. Never invents a number.
    Strict-less-than-or-equal comparison so a same-timestamp BUY fill is
    included (paper-forward emits BUY fills before exits).
    """

    if not symbol or not isinstance(fills, list):
        return None
    target_symbol = str(symbol).upper()
    cutoff = str(before_iso or "")
    total_qty = 0.0
    total_value = 0.0
    for fill in fills:
        if not isinstance(fill, dict):
            continue
        if str(fill.get("side") or "").upper() != "BUY":
            continue
        if str(fill.get("symbol") or "").upper() != target_symbol:
            continue
        filled_at = str(fill.get("filled_at") or "")
        if cutoff and filled_at and filled_at > cutoff:
            continue
        qty = _safe_float(fill.get("quantity"))
        price = _safe_float(fill.get("fill_price"))
        if qty is None or price is None or qty <= 0.0:
            continue
        total_qty += qty
        total_value += qty * price
    if total_qty <= 0.0:
        return None
    return total_value / total_qty


def _return_pct(*, entry_price: Any, exit_price: Any) -> float | None:
    entry = _safe_float(entry_price)
    exit_ = _safe_float(exit_price)
    if entry is None or exit_ is None or entry == 0.0:
        return None
    return (exit_ - entry) / entry


def _format_pct(value: Any) -> str:
    parsed = _safe_float(value)
    if parsed is None:
        return "n/a"
    return f"{parsed * 100.0:.2f}%"


def _load_json(path: Path, *, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        text = path.read_text(encoding="utf-8").strip()
    except Exception:
        return default
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default


# --- Local-timezone display helpers ----------------------------------------


def resolve_local_tz(name: str | None = None) -> Any:
    """Return a ``ZoneInfo`` for ``name`` (or env / default) or ``None``.

    Falls back to ``timezone.utc`` only as a last resort: callers should treat
    a ``None`` return as "do not enrich local-time fields" so UTC archive ids
    remain authoritative.
    """

    if ZoneInfo is None:
        return None
    candidate = name or os.environ.get(CRYPTO_LOCAL_TZ_ENV) or DEFAULT_CRYPTO_LOCAL_TZ
    try:
        return ZoneInfo(str(candidate))
    except ZoneInfoNotFoundError:
        return None
    except Exception:
        return None


def _resolve_local_tz_name() -> str:
    return str(os.environ.get(CRYPTO_LOCAL_TZ_ENV) or DEFAULT_CRYPTO_LOCAL_TZ)


def local_tz_label(tz_name: str) -> str:
    """Return a human-friendly tz abbreviation (e.g. ``ART`` for Buenos Aires).

    Falls back to ``%Z`` / numeric offset when the tz is not in the curated
    map; callers can therefore display a meaningful badge regardless of the
    user-configured tz.
    """

    text = str(tz_name or "").strip()
    if text in _LOCAL_TZ_ABBREV:
        return _LOCAL_TZ_ABBREV[text]
    tz = resolve_local_tz(text)
    if tz is None:
        return text or "UTC"
    sample = datetime(2026, 1, 1, tzinfo=timezone.utc).astimezone(tz)
    abbrev = sample.strftime("%Z")
    if abbrev and not abbrev.startswith(("+", "-")):
        return abbrev
    # Numeric offset like "-03": prefer the last segment of the IANA name.
    short = text.split("/")[-1] if "/" in text else text
    return short or abbrev or "UTC"


def local_display_for_iso(iso_text: str, *, tz_name: str) -> dict[str, Any] | None:
    """Project ``iso_text`` (UTC ISO-8601) to a small local-display dict.

    Returns ``None`` when ``iso_text`` is empty or unparseable. The output is
    intentionally minimal so the notifier and the dashboard can render
    ``Hora local: HH:MM ART`` and ``UTC: HH:MM`` without re-implementing tz
    logic.
    """

    text = str(iso_text or "").strip()
    if not text:
        return None
    try:
        # ``fromisoformat`` accepts both naive and tz-aware ISO strings on Py 3.11+.
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment_utc = moment.astimezone(timezone.utc)
    tz = resolve_local_tz(tz_name)
    if tz is None:
        local_dt = moment_utc
        label = "UTC"
    else:
        local_dt = moment_utc.astimezone(tz)
        label = local_tz_label(tz_name)
    return {
        "tz": tz_name,
        "tz_label": label,
        "time_local": local_dt.strftime("%H:%M"),
        "datetime_local": local_dt.strftime("%Y-%m-%d %H:%M"),
        "time_utc": moment_utc.strftime("%H:%M"),
        "datetime_utc": moment_utc.strftime("%Y-%m-%d %H:%M"),
        "iso_local": local_dt.isoformat(),
        "iso_utc": moment_utc.isoformat(),
    }


def _local_display_for(iso_text: str, *, tz_name: str) -> dict[str, Any] | None:
    """Internal alias kept for symmetry with ``_enrich_events_with_local_display``."""

    return local_display_for_iso(iso_text, tz_name=tz_name)


def _enrich_events_with_local_display(
    *, events: list[dict[str, Any]], tz_name: str
) -> None:
    """Annotate each event in-place with ``local_tz`` / ``created_at_local``.

    The original ``created_at`` UTC ISO field is preserved untouched so
    archive folder naming and downstream UTC-only consumers stay stable.
    Per-event ``metadata.occurred_at`` is also projected when present.
    """

    for event in events:
        if not isinstance(event, dict):
            continue
        event["local_tz"] = tz_name
        created_local = local_display_for_iso(
            str(event.get("created_at") or ""), tz_name=tz_name
        )
        if created_local is not None:
            event["created_at_local"] = created_local
        metadata = event.get("metadata")
        if isinstance(metadata, dict):
            occurred_iso = metadata.get("occurred_at")
            if isinstance(occurred_iso, str) and occurred_iso:
                occurred_local = local_display_for_iso(occurred_iso, tz_name=tz_name)
                if occurred_local is not None:
                    metadata["occurred_at_local"] = occurred_local
