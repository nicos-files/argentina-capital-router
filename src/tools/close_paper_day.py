from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import pandas as pd

from src.decision_intel.contracts.metadata_models import CURRENT_SCHEMA_VERSION, MIN_READER_VERSION
from src.decision_intel.positions.positions_store import PositionsSnapshot, load_positions_snapshot
from src.decision_intel.utils.io import ensure_run_dir, validate_run_write_path


ROOT = Path(__file__).resolve().parents[2]


def close_paper_day(
    run_id: str,
    base_path: str = "runs",
    mark_date: str | None = None,
) -> Path:
    run_root = ensure_run_dir(run_id, base_path=base_path)
    rec_path = run_root / "artifacts" / f"recommendation.outputs.v{CURRENT_SCHEMA_VERSION}.json"
    results_path = run_root / "artifacts" / f"execution.results.v{CURRENT_SCHEMA_VERSION}.json"
    before_path = run_root / "artifacts" / "positions_snapshot_before.json"
    after_path = run_root / "artifacts" / "positions_snapshot_after.json"

    if not rec_path.exists():
        raise ValueError(f"recommendation.outputs missing: {rec_path}")
    if not results_path.exists():
        raise ValueError(f"execution.results missing: {results_path}")
    if not before_path.exists():
        raise ValueError(f"positions_snapshot_before missing: {before_path}")
    if not after_path.exists():
        raise ValueError(f"positions_snapshot_after missing: {after_path}")

    rec_payload = json.loads(rec_path.read_text(encoding="utf-8"))
    results_payload = json.loads(results_path.read_text(encoding="utf-8"))
    before_snapshot = _load_snapshot(before_path)
    after_snapshot = _load_snapshot(after_path)

    effective_mark_date = mark_date or rec_payload.get("execution_date") or rec_payload.get("asof_date")
    price_map = _load_price_map(effective_mark_date)
    price_map.update(_recommendation_price_map(rec_payload))

    equity_before = _snapshot_equity(before_snapshot, price_map)
    equity_after = _snapshot_equity(after_snapshot, price_map)
    fees_total = sum(float(row.get("fees_actual") or 0.0) for row in results_payload.get("results", []))
    gross_delta = equity_after - equity_before + fees_total
    net_delta = equity_after - equity_before

    payload = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "reader_min_version": MIN_READER_VERSION,
        "run_id": run_id,
        "mark_date": effective_mark_date,
        "equity_before_usd": round(equity_before, 6),
        "equity_after_usd": round(equity_after, 6),
        "gross_pnl_usd": round(gross_delta, 6),
        "fees_total_usd": round(fees_total, 6),
        "net_pnl_usd": round(net_delta, 6),
        "positions_before_count": len(before_snapshot.positions),
        "positions_after_count": len(after_snapshot.positions),
        "cash_before_usd": round(_cash_usd(before_snapshot), 6),
        "cash_after_usd": round(_cash_usd(after_snapshot), 6),
    }

    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    out_path = validate_run_write_path(
        run_id,
        run_root / "artifacts" / f"paper.day_close.v{CURRENT_SCHEMA_VERSION}.json",
        base_path=base_path,
    )
    out_path.write_text(serialized, encoding="utf-8")

    manifest_path = run_root / "manifests" / f"run_manifest.v{CURRENT_SCHEMA_VERSION}.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.setdefault("artifact_index", [])
        _upsert_artifact(
            manifest["artifact_index"],
            {
                "name": "paper.day_close",
                "type": "paper.day_close",
                "path": out_path.resolve().relative_to(run_root.resolve()).as_posix(),
                "schema_version": CURRENT_SCHEMA_VERSION,
                "content_hash": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
            },
        )
        manifest_path.write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
            encoding="utf-8",
        )

    print("[CLOSE-PAPER-DAY] SUCCESS")
    print(f"- run_id: {run_id}")
    print(f"- mark_date: {effective_mark_date}")
    print(f"- equity_before_usd: {equity_before:.2f}")
    print(f"- equity_after_usd: {equity_after:.2f}")
    print(f"- fees_total_usd: {fees_total:.2f}")
    print(f"- gross_pnl_usd: {gross_delta:.2f}")
    print(f"- net_pnl_usd: {net_delta:.2f}")
    print(f"- artifact: {out_path}")
    return out_path


def _load_snapshot(path: Path) -> PositionsSnapshot:
    temp_root = path.parents[3]
    return load_positions_snapshot(temp_root) if path.name == "positions.json" else _snapshot_from_payload(json.loads(path.read_text(encoding="utf-8")))


def _snapshot_from_payload(payload: Dict[str, Any]) -> PositionsSnapshot:
    temp_root = ROOT / ".tmp_snapshot_loader_unused"
    positions_path = temp_root / "data" / "results" / "positions.json"
    positions_path.parent.mkdir(parents=True, exist_ok=True)
    positions_path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    return load_positions_snapshot(temp_root)


def _load_price_map(mark_date: str | None) -> Dict[str, float]:
    if not mark_date:
        return {}
    features_path = ROOT / "data" / "processed" / "features" / mark_date.replace("-", "/") / "features.parquet"
    if not features_path.exists():
        return {}
    df = pd.read_parquet(features_path, columns=["ticker", "close"])
    df = df.dropna(subset=["ticker", "close"]).drop_duplicates(subset=["ticker"], keep="last")
    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    return {row["ticker"]: float(row["close"]) for _, row in df.iterrows()}


def _recommendation_price_map(payload: Dict[str, Any]) -> Dict[str, float]:
    price_map: Dict[str, float] = {}
    for item in payload.get("recommendations", []):
        asset_id = item.get("asset_id") or item.get("ticker")
        price = item.get("price_used")
        if isinstance(asset_id, str) and isinstance(price, (int, float)):
            price_map[asset_id.strip().upper()] = float(price)
    return price_map


def _snapshot_equity(snapshot: PositionsSnapshot, price_map: Dict[str, float]) -> float:
    equity = _cash_usd(snapshot)
    for asset_id, position in snapshot.positions.items():
        mark = price_map.get(asset_id) or position.avg_price
        fx_rate = position.fx_rate_used if position.fx_rate_used is not None else (1.0 if position.currency == "USD" else None)
        if position.currency != "USD" and fx_rate is None:
            continue
        equity += float(position.qty) * float(mark) * float(fx_rate or 1.0)
    return equity


def _cash_usd(snapshot: PositionsSnapshot) -> float:
    total = float(snapshot.cash_by_currency.get("USD") or 0.0)
    for currency, amount in snapshot.cash_by_currency.items():
        if currency == "USD":
            continue
        # Non-USD cash is ignored until a reliable FX source is available.
        _ = amount
    return total


def _upsert_artifact(artifact_index: list[dict[str, Any]], candidate: dict[str, Any]) -> None:
    for idx, entry in enumerate(artifact_index):
        if entry.get("name") == candidate.get("name") and entry.get("path") == candidate.get("path"):
            artifact_index[idx] = {**entry, **candidate}
            return
    artifact_index.append(candidate)
