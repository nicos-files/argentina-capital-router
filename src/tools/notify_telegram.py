from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib import error, request

from src.decision_intel.contracts.metadata_models import CURRENT_SCHEMA_VERSION


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BOT_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
DEFAULT_CHAT_ID_ENV = "TELEGRAM_CHAT_ID"


def notify_telegram(
    run_id: str,
    base_path: str = "runs",
    bot_token: str | None = None,
    chat_id: str | None = None,
    include_close: bool = True,
    timeout_sec: int = 20,
) -> dict[str, Any]:
    resolved_token = bot_token or os.getenv(DEFAULT_BOT_TOKEN_ENV)
    resolved_chat_id = chat_id or os.getenv(DEFAULT_CHAT_ID_ENV)
    if not resolved_token:
        raise ValueError(f"Missing Telegram bot token. Set {DEFAULT_BOT_TOKEN_ENV} or pass --bot-token")
    if not resolved_chat_id:
        raise ValueError(f"Missing Telegram chat id. Set {DEFAULT_CHAT_ID_ENV} or pass --chat-id")

    message = build_telegram_message(run_id=run_id, base_path=base_path, include_close=include_close)
    response = send_telegram_message(
        bot_token=resolved_token,
        chat_id=resolved_chat_id,
        text=message,
        timeout_sec=timeout_sec,
    )
    return {
        "ok": True,
        "run_id": run_id,
        "chat_id": _mask_chat_id(resolved_chat_id),
        "message_length": len(message),
        "telegram_response_ok": bool(response.get("ok")),
    }


def build_telegram_message(run_id: str, base_path: str = "runs", include_close: bool = True) -> str:
    run_root = ROOT / base_path / run_id
    rec_path = run_root / "artifacts" / f"recommendation.outputs.v{CURRENT_SCHEMA_VERSION}.json"
    if not rec_path.exists():
        raise FileNotFoundError(f"recommendation.outputs missing: {rec_path}")

    payload = json.loads(rec_path.read_text(encoding="utf-8"))
    lines = [
        f"quant-trading-bot | run {run_id}",
        f"Asof: {payload.get('asof_date') or 'n/a'}",
    ]
    execution_date = payload.get("execution_date")
    execution_hour = payload.get("execution_hour")
    if execution_date or execution_hour:
        lines.append(f"Ejecucion: {execution_date or 'n/a'} {execution_hour or ''}".strip())

    recommendations = payload.get("recommendations", [])
    lines.extend(_format_horizon_lines("INTRADAY", recommendations, payload.get("cash_summary", {})))
    lines.extend(_format_horizon_lines("LONG_TERM", recommendations, payload.get("cash_summary", {})))

    if include_close:
        close_lines = _format_close_lines(run_root)
        if close_lines:
            lines.extend(close_lines)

    return "\n".join(lines)


def send_telegram_message(bot_token: str, chat_id: str, text: str, timeout_sec: int = 20) -> dict[str, Any]:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout_sec) as response:
            body = response.read().decode("utf-8")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Telegram send failed: HTTP {exc.code} {body}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Telegram send failed: {exc.reason}") from exc

    parsed = json.loads(body)
    if not parsed.get("ok"):
        raise RuntimeError(f"Telegram send failed: {parsed}")
    return parsed


def _format_horizon_lines(
    horizon: str,
    recommendations: list[dict[str, Any]],
    cash_summary: dict[str, Any],
) -> list[str]:
    lines = [f"{horizon}:"]
    horizon_items = [item for item in recommendations if item.get("horizon") == horizon and item.get("action") == "BUY"]
    if not horizon_items:
        cash_retained = ((cash_summary or {}).get(horizon, {}) or {}).get("cash_retained_usd")
        if cash_retained is None:
            lines.append("- sin compras")
        else:
            lines.append(f"- sin compras | cash_retained_usd={float(cash_retained):.2f}")
        return lines

    for item in sorted(
        horizon_items,
        key=lambda entry: float(entry.get("expected_return_net_pct") or 0.0),
        reverse=True,
    )[:5]:
        lines.append(
            f"- BUY {item.get('asset_id')} qty={float(item.get('qty_target') or 0.0):.6f} "
            f"usd={float(item.get('usd_target_effective') or 0.0):.2f} "
            f"net={float(item.get('expected_return_net_pct') or 0.0):.4f} "
            f"fees={float(item.get('fees_estimated_usd') or 0.0):.2f}"
        )

    cash_info = ((cash_summary or {}).get(horizon, {}) or {})
    cash_retained = cash_info.get("cash_retained_usd")
    if cash_retained is not None:
        lines.append(f"- cash_retained_usd={float(cash_retained):.2f}")
    return lines


def _format_close_lines(run_root: Path) -> list[str]:
    close_path = run_root / "artifacts" / f"paper.day_close.v{CURRENT_SCHEMA_VERSION}.json"
    if not close_path.exists():
        return []
    payload = json.loads(close_path.read_text(encoding="utf-8"))
    return [
        "CIERRE:",
        f"- equity_before_usd={float(payload.get('equity_before_usd') or 0.0):.2f}",
        f"- equity_after_usd={float(payload.get('equity_after_usd') or 0.0):.2f}",
        f"- net_pnl_usd={float(payload.get('net_pnl_usd') or 0.0):.2f}",
        f"- fees_total_usd={float(payload.get('fees_total_usd') or 0.0):.2f}",
    ]


def _mask_chat_id(chat_id: str) -> str:
    chat_id = str(chat_id)
    if len(chat_id) <= 4:
        return "*" * len(chat_id)
    return ("*" * max(len(chat_id) - 4, 0)) + chat_id[-4:]
