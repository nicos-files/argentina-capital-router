from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Tuple


@dataclass(frozen=True)
class PositionRecord:
    qty: float
    avg_price: float
    broker: str
    currency: str
    fx_rate_used: float | None = None
    fx_rate_source: str | None = None


@dataclass(frozen=True)
class PositionsSnapshot:
    positions: Dict[str, PositionRecord]
    cash_by_currency: Dict[str, float]
    cash_by_broker: Dict[str, Dict[str, float]]


def load_positions(base_root: Path) -> Tuple[Dict[str, PositionRecord], Dict[str, float]]:
    snapshot = load_positions_snapshot(base_root)
    return snapshot.positions, snapshot.cash_by_currency


def load_positions_snapshot(base_root: Path) -> PositionsSnapshot:
    positions_path = base_root / "data" / "results" / "positions.json"
    if not positions_path.exists():
        positions_path.parent.mkdir(parents=True, exist_ok=True)
        example = {
            "positions": [
                {
                    "asset_id": "NVDA",
                    "broker": "iol",
                    "qty": 2.0,
                    "avg_price": 480.0,
                    "currency": "USD",
                }
            ],
            "cash": {"USD": 600.0},
            "cash_by_broker": {"iol": {"USD": 600.0}},
        }
        positions_path.write_text(
            json.dumps(example, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
            encoding="utf-8",
        )
    payload = json.loads(positions_path.read_text(encoding="utf-8"))
    positions_raw: list[dict[str, Any]] = []
    cash_raw: dict[str, Any] = {}
    cash_by_broker_raw: dict[str, Any] = {}
    if isinstance(payload, list):
        positions_raw = payload
    elif isinstance(payload, dict):
        positions_raw = payload.get("positions") if isinstance(payload.get("positions"), list) else []
        cash_raw = payload.get("cash") if isinstance(payload.get("cash"), dict) else {}
        cash_by_broker_raw = payload.get("cash_by_broker") if isinstance(payload.get("cash_by_broker"), dict) else {}

    positions: Dict[str, PositionRecord] = {}
    for item in positions_raw:
        if not isinstance(item, dict):
            continue
        asset_id = item.get("asset_id") or item.get("ticker")
        if not isinstance(asset_id, str) or not asset_id.strip():
            continue
        qty = item.get("qty")
        avg_price = item.get("avg_price")
        if not _is_number(qty) or not _is_number(avg_price):
            continue
        broker = item.get("broker") if isinstance(item.get("broker"), str) else "generic_us"
        currency = item.get("currency") if isinstance(item.get("currency"), str) else "USD"
        fx_rate_used = item.get("fx_rate_used")
        fx_rate_source = item.get("fx_rate_source")
        positions[asset_id.strip().upper()] = PositionRecord(
            qty=float(qty),
            avg_price=float(avg_price),
            broker=broker.strip(),
            currency=currency.strip().upper(),
            fx_rate_used=float(fx_rate_used) if _is_number(fx_rate_used) else None,
            fx_rate_source=fx_rate_source.strip() if isinstance(fx_rate_source, str) else None,
        )

    cash_by_currency: Dict[str, float] = {}
    for key, value in cash_raw.items():
        if not isinstance(key, str) or not key.strip():
            continue
        if not _is_number(value):
            continue
        cash_by_currency[key.strip().upper()] = float(value)

    cash_by_broker: Dict[str, Dict[str, float]] = {}
    for broker, payload_value in cash_by_broker_raw.items():
        if not isinstance(broker, str) or not broker.strip():
            continue
        if not isinstance(payload_value, dict):
            continue
        broker_key = broker.strip()
        broker_cash: Dict[str, float] = {}
        for currency, amount in payload_value.items():
            if not isinstance(currency, str) or not currency.strip():
                continue
            if not _is_number(amount):
                continue
            broker_cash[currency.strip().upper()] = float(amount)
        if broker_cash:
            cash_by_broker[broker_key] = broker_cash

    return PositionsSnapshot(
        positions=positions,
        cash_by_currency=cash_by_currency,
        cash_by_broker=cash_by_broker,
    )


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def save_positions_snapshot(
    run_id: str | None,
    snapshot: PositionsSnapshot,
    base_path: str = "runs",
    base_root: Path | None = None,
    filename: str | None = None,
    artifact_name: str = "positions.snapshot.after",
    artifact_type: str = "positions.snapshot.after",
    asof_date: str | None = None,
    execution_date: str | None = None,
    execution_hour: str | None = None,
    include_metadata: bool = True,
) -> Tuple[Path, Dict[str, Any]]:
    root = base_root or Path(__file__).resolve().parents[3]
    payload = _snapshot_payload(snapshot, include_metadata, asof_date, execution_date, execution_hour)
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    if run_id:
        run_root = Path(base_path) / run_id
        target = run_root / "artifacts" / (filename or "positions_snapshot_after.json")
    else:
        if not filename:
            raise ValueError("filename required when run_id is None")
        target = root / filename

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(serialized, encoding="utf-8")

    entry = {}
    if run_id:
        run_root_abs = (Path(base_path) / run_id).resolve()
        entry = {
            "name": artifact_name,
            "type": artifact_type,
            "path": target.resolve().relative_to(run_root_abs).as_posix(),
            "schema_version": "1.0.0",
        }
    return target, entry


def _snapshot_payload(
    snapshot: PositionsSnapshot,
    include_metadata: bool,
    asof_date: str | None,
    execution_date: str | None,
    execution_hour: str | None,
) -> Dict[str, Any]:
    positions_list = []
    for asset_id, record in snapshot.positions.items():
        entry: Dict[str, Any] = {
            "asset_id": asset_id,
            "broker": record.broker,
            "qty": record.qty,
            "avg_price": record.avg_price,
            "currency": record.currency,
        }
        if record.fx_rate_used is not None:
            entry["fx_rate_used"] = record.fx_rate_used
        if record.fx_rate_source is not None:
            entry["fx_rate_source"] = record.fx_rate_source
        positions_list.append(entry)

    payload: Dict[str, Any] = {
        "positions": positions_list,
        "cash": snapshot.cash_by_currency,
        "cash_by_broker": snapshot.cash_by_broker,
    }
    if include_metadata:
        payload.update(
            {
                "asof_date": asof_date,
                "execution_date": execution_date,
                "execution_hour": execution_hour,
            }
        )
    return payload
