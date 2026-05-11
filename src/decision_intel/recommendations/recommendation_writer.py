from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from src.decision_intel.contracts.metadata_models import CURRENT_SCHEMA_VERSION, MIN_READER_VERSION
from src.decision_intel.contracts.recommendations import (
    RECOMMENDATION_ARTIFACT_NAME,
    RECOMMENDATION_ARTIFACT_TYPE,
    RecommendationOutput,
)
from src.decision_intel.policies.topk_net_after_fees import (
    CAPITAL_USD,
    CASH_POLICY,
    POLICY_ID,
    POLICY_VERSION,
    apply_topk_net_after_fees,
)
from src.decision_intel.positions.positions_store import load_positions_snapshot
from src.decision_intel.utils.io import ensure_run_dir, validate_run_write_path


def write_recommendations(
    run_id: str,
    base_path: str = "runs",
    top_k: int = 10,
    execution_date: str | None = None,
    execution_hour: str | None = None,
) -> Tuple[Path, Dict[str, Any]]:
    run_root = ensure_run_dir(run_id, base_path=base_path)
    base_root = Path(__file__).resolve().parents[3]
    manifest_path = run_root / "manifests" / f"run_manifest.v{CURRENT_SCHEMA_VERSION}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    decision_path = _find_artifact_path(run_root, manifest, "decision.outputs")
    decision_payload = json.loads(Path(decision_path).read_text(encoding="utf-8"))
    decisions = decision_payload.get("decisions", [])
    horizon = decision_payload.get("horizon")
    asof_date = _extract_asof_date(decision_payload, decisions)
    price_map = _load_price_map(base_root, asof_date)
    snapshot = load_positions_snapshot(base_root)
    positions = snapshot.positions
    recommendations = apply_topk_net_after_fees(
        decisions,
        asof_date=asof_date,
        execution_date=execution_date,
        execution_hour=execution_hour,
        price_map=price_map,
        positions=positions,
        cash_by_currency=snapshot.cash_by_currency,
        cash_by_broker=snapshot.cash_by_broker,
    )
    horizons = {item.get("horizon") for item in recommendations if item.get("horizon")}
    if len(horizons) > 1:
        horizon = "MIXED"
    elif horizons:
        horizon = horizons.pop()

    payload = RecommendationOutput.build(
        run_id=run_id,
        horizon=horizon,
        asof_date=asof_date,
        policy_id=POLICY_ID,
        policy_version=POLICY_VERSION,
        constraints=[],
        sizing_rule="weights.normalized_pct",
        recommendations=recommendations,
        cash_summary=_build_cash_summary(recommendations, snapshot, CAPITAL_USD),
        cash_policy=CASH_POLICY,
        execution_date=execution_date,
        execution_hour=execution_hour,
        metadata={},
    ).to_payload()
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    output_path = validate_run_write_path(
        run_id,
        run_root / "artifacts" / f"recommendation.outputs.v{CURRENT_SCHEMA_VERSION}.json",
        base_path=base_path,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(serialized, encoding="utf-8")

    run_root_abs = run_root.resolve()
    entry = {
        "name": RECOMMENDATION_ARTIFACT_NAME,
        "type": RECOMMENDATION_ARTIFACT_TYPE,
        "path": output_path.resolve().relative_to(run_root_abs).as_posix(),
        "schema_version": CURRENT_SCHEMA_VERSION,
        "content_hash": _hash_text(serialized),
    }

    manifest.setdefault("artifact_index", [])
    _upsert_artifact(manifest["artifact_index"], entry)
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )
    return output_path, entry


def _extract_asof_date(payload: Dict[str, Any], decisions: List[Dict[str, Any]]) -> str | None:
    asof_date = payload.get("asof_date")
    if isinstance(asof_date, str) and asof_date:
        return asof_date
    for decision in decisions:
        outputs = decision.get("outputs")
        if not isinstance(outputs, dict):
            continue
        asof_date = outputs.get("asof_date")
        if isinstance(asof_date, str) and asof_date:
            return asof_date
    return None


def _build_cash_summary(
    recommendations: List[Dict[str, Any]],
    snapshot: Any,
    capital_by_horizon: Dict[str, float],
) -> Dict[str, Dict[str, Any]]:
    summary: Dict[str, Dict[str, Any]] = {}
    has_snapshot_cash = bool(getattr(snapshot, "cash_by_currency", {})) or bool(getattr(snapshot, "cash_by_broker", {}))
    cash_source = "positions_snapshot" if has_snapshot_cash else "policy_capital"
    snapshot_cash_usd = _snapshot_cash_usd(snapshot)
    for horizon, capital in capital_by_horizon.items():
        horizon_items = [item for item in recommendations if item.get("horizon") == horizon]
        buy_used = sum(float(item.get("cash_used_usd") or 0.0) for item in horizon_items if item.get("action") == "BUY")
        effective_capital = min(float(capital), snapshot_cash_usd) if has_snapshot_cash else float(capital)
        retained = max(effective_capital - buy_used, 0.0)
        summary[horizon] = {
            "capital_usd": effective_capital,
            "cash_used_usd": buy_used,
            "cash_retained_usd": retained,
            "cash_source": cash_source,
        }
    return summary


def _snapshot_cash_usd(snapshot: Any) -> float:
    cash_by_currency = getattr(snapshot, "cash_by_currency", {}) or {}
    if "USD" in cash_by_currency:
        return float(cash_by_currency.get("USD") or 0.0)
    cash_by_broker = getattr(snapshot, "cash_by_broker", {}) or {}
    return sum(float((currencies or {}).get("USD") or 0.0) for currencies in cash_by_broker.values())


def _load_price_map(base_root: Path, asof_date: str | None) -> Dict[str, float]:
    if not asof_date:
        return {}
    features_path = base_root / "data" / "processed" / "features" / asof_date.replace("-", "/") / "features.parquet"
    if not features_path.exists():
        print(f"[WARN] recommendation price source missing: {features_path}")
        return {}
    import pandas as pd

    df = pd.read_parquet(features_path, columns=["ticker", "close"])
    df = df.dropna(subset=["ticker", "close"])
    df["ticker"] = df["ticker"].astype(str).str.strip().str.upper()
    df = df.drop_duplicates(subset=["ticker"], keep="last")
    return {row["ticker"]: float(row["close"]) for _, row in df.iterrows()}


def _find_artifact_path(run_root: Path, manifest: Dict[str, Any], name: str) -> str:
    for entry in manifest.get("artifact_index", []):
        if entry.get("name") == name:
            path_value = entry.get("path")
            if not path_value:
                raise ValueError(f"artifact {name} path missing in manifest")
            path = Path(path_value)
            return str(path if path.is_absolute() else run_root / path)
    raise ValueError(f"artifact {name} not found in manifest")


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _upsert_artifact(artifact_index: List[Dict[str, Any]], candidate: Dict[str, Any]) -> None:
    for index, entry in enumerate(artifact_index):
        if (
            entry.get("name") == candidate["name"]
            and entry.get("type") == candidate["type"]
            and entry.get("path") == candidate["path"]
        ):
            artifact_index[index] = {**entry, **candidate}
            return
    artifact_index.append(candidate)
