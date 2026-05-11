from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from .crypto_paper_models import CryptoPaperExecutionConfig, CryptoPaperExitEvent, CryptoPaperPosition


def _exit_id_stamp(value: datetime | None) -> str:
    moment = value if isinstance(value, datetime) else datetime.utcnow()
    if moment.tzinfo is not None:
        moment = moment.astimezone().replace(tzinfo=None)
    return moment.strftime("%Y%m%dT%H%M%S")


def evaluate_crypto_exit_triggers(
    positions: list[CryptoPaperPosition],
    candles_by_symbol: dict[str, Any],
    as_of: datetime,
    config: CryptoPaperExecutionConfig,
    latest_quotes: dict[str, Any] | None = None,
) -> list[CryptoPaperExitEvent]:
    """Evaluate stop-loss / take-profit exits for open long crypto paper positions.

    Long-only paper exits. Two evaluation paths, in order:

    1. Candle path: scan ``candles_by_symbol[position.symbol]`` candles strictly
       after ``position.updated_at``. ``high >= take_profit`` => TAKE_PROFIT;
       ``low <= stop_loss`` => STOP_LOSS. Same-candle conflict: STOP_LOSS wins.
    2. Quote fallback: if the candle path produced no event for the position
       (missing/incomplete candles, or the latest closed candle did not yet
       cross), fall back to the latest quote / position last_price.

       - For TAKE_PROFIT detection, use ``bid`` if present (conservative since
         a long-close sells into the bid), else fall back to ``last_price`` /
         ``position.last_price``.
       - For STOP_LOSS detection, use ``last_price`` / ``position.last_price``
         (or ``bid`` if last_price is missing).

    Same-tick conflict in the quote fallback: STOP_LOSS wins. The fallback
    fires the exit at the SL/TP threshold (same convention as the candle path)
    so paper-trading semantics stay consistent and conservative.
    """

    events: list[CryptoPaperExitEvent] = []
    stamp = _exit_id_stamp(as_of)
    quotes = latest_quotes or {}
    for position in positions:
        quantity = float(position.quantity or 0.0)
        if quantity <= 0.0:
            continue
        stop_loss = _optional_float(position.metadata.get("stop_loss"))
        take_profit = _optional_float(position.metadata.get("take_profit"))
        if stop_loss is None and take_profit is None:
            continue

        candle_event = _scan_candles_for_exit(
            position=position,
            rows=_normalize_candles(candles_by_symbol.get(position.symbol)),
            stop_loss=stop_loss,
            take_profit=take_profit,
            as_of=as_of,
            stamp=stamp,
            event_index=len(events) + 1,
            config=config,
        )
        if candle_event is not None:
            events.append(candle_event)
            continue

        quote_event = _scan_quote_for_exit(
            position=position,
            quote=quotes.get(position.symbol),
            stop_loss=stop_loss,
            take_profit=take_profit,
            as_of=as_of,
            stamp=stamp,
            event_index=len(events) + 1,
            config=config,
        )
        if quote_event is not None:
            events.append(quote_event)
    return events


def _scan_candles_for_exit(
    *,
    position: CryptoPaperPosition,
    rows: list[dict[str, Any]],
    stop_loss: float | None,
    take_profit: float | None,
    as_of: datetime,
    stamp: str,
    event_index: int,
    config: CryptoPaperExecutionConfig,
) -> CryptoPaperExitEvent | None:
    if not rows:
        return None
    quantity = float(position.quantity or 0.0)
    entry_time = position.updated_at
    for row in rows:
        timestamp = row.get("timestamp")
        if entry_time is not None and isinstance(timestamp, datetime) and timestamp <= entry_time:
            continue
        low = row.get("low")
        high = row.get("high")
        if low is None or high is None:
            continue
        stop_hit = stop_loss is not None and float(low) <= float(stop_loss)
        take_hit = take_profit is not None and float(high) >= float(take_profit)
        if not stop_hit and not take_hit:
            continue
        if stop_hit:
            trigger_price = float(stop_loss)
            reason = "STOP_LOSS"
        else:
            trigger_price = float(take_profit)
            reason = "TAKE_PROFIT"
        return CryptoPaperExitEvent(
            exit_id=f"crypto-exit-{position.symbol}-{stamp}-{event_index:04d}",
            symbol=position.symbol,
            position_quantity_before=quantity,
            exit_quantity=quantity if bool(config.exit_full_position) else quantity,
            exit_reason=reason,
            trigger_price=trigger_price,
            fill_price=trigger_price,
            gross_notional=quantity * trigger_price,
            fee=0.0,
            slippage=0.0,
            realized_pnl=0.0,
            exited_at=timestamp if isinstance(timestamp, datetime) else as_of,
            source="stop_take_evaluator",
            metadata={
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "same_candle_conflict": bool(stop_hit and take_hit),
                "avg_entry_price": float(position.avg_entry_price),
            },
        )
    return None


def _scan_quote_for_exit(
    *,
    position: CryptoPaperPosition,
    quote: Any,
    stop_loss: float | None,
    take_profit: float | None,
    as_of: datetime,
    stamp: str,
    event_index: int,
    config: CryptoPaperExecutionConfig,
) -> CryptoPaperExitEvent | None:
    last_price = _quote_last_price(quote)
    if last_price is None and position.last_price is not None:
        last_price = float(position.last_price)
    bid = _quote_bid(quote)

    take_check_price = bid if bid is not None else last_price
    stop_check_price = last_price if last_price is not None else bid

    if take_check_price is None and stop_check_price is None:
        return None

    stop_hit = (
        stop_loss is not None
        and stop_check_price is not None
        and float(stop_check_price) <= float(stop_loss)
    )
    take_hit = (
        take_profit is not None
        and take_check_price is not None
        and float(take_check_price) >= float(take_profit)
    )
    if not stop_hit and not take_hit:
        return None

    if stop_hit:
        trigger_price = float(stop_loss)
        reason = "STOP_LOSS"
    else:
        trigger_price = float(take_profit)
        reason = "TAKE_PROFIT"

    quantity = float(position.quantity or 0.0)
    return CryptoPaperExitEvent(
        exit_id=f"crypto-exit-{position.symbol}-{stamp}-{event_index:04d}",
        symbol=position.symbol,
        position_quantity_before=quantity,
        exit_quantity=quantity if bool(config.exit_full_position) else quantity,
        exit_reason=reason,
        trigger_price=trigger_price,
        fill_price=trigger_price,
        gross_notional=quantity * trigger_price,
        fee=0.0,
        slippage=0.0,
        realized_pnl=0.0,
        exited_at=as_of,
        source="stop_take_quote_fallback",
        metadata={
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "same_tick_conflict": bool(stop_hit and take_hit),
            "avg_entry_price": float(position.avg_entry_price),
            "fallback": "quote",
            "last_price": last_price,
            "bid": bid,
            "take_check_price": take_check_price,
            "stop_check_price": stop_check_price,
        },
    )


def _quote_last_price(quote: Any) -> float | None:
    if isinstance(quote, dict):
        for key in ("last_price", "ask"):
            if quote.get(key) is not None:
                value = _optional_float(quote.get(key))
                if value is not None:
                    return value
    if isinstance(quote, (int, float)):
        return float(quote)
    return None


def _quote_bid(quote: Any) -> float | None:
    if isinstance(quote, dict) and quote.get("bid") is not None:
        return _optional_float(quote.get("bid"))
    return None


def _normalize_candles(payload: Any) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if isinstance(payload, pd.DataFrame):
        rows = []
        for _, row in payload.sort_values("date").iterrows():
            rows.append(
                {
                    "timestamp": _to_datetime(row.get("date")),
                    "open": _optional_float(row.get("open")),
                    "high": _optional_float(row.get("high")),
                    "low": _optional_float(row.get("low")),
                    "close": _optional_float(row.get("close")),
                    "volume": _optional_float(row.get("volume")),
                }
            )
        return rows
    if isinstance(payload, list):
        rows = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "timestamp": _to_datetime(item.get("timestamp") or item.get("date")),
                    "open": _optional_float(item.get("open")),
                    "high": _optional_float(item.get("high")),
                    "low": _optional_float(item.get("low")),
                    "close": _optional_float(item.get("close")),
                    "volume": _optional_float(item.get("volume")),
                }
            )
        return sorted(rows, key=lambda row: row.get("timestamp") or datetime.min)
    return []


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if value is None:
        return None
    try:
        return pd.Timestamp(value).to_pydatetime()
    except Exception:
        return None
