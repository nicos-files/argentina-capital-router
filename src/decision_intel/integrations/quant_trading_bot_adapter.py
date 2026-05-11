from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from src.decision_intel.contracts.metadata_models import CURRENT_SCHEMA_VERSION, MIN_READER_VERSION
from src.decision_intel.decision.output_writer import write_decision_outputs
from src.decision_intel.evaluation.metrics_writer import write_evaluation_metrics
from src.decision_intel.exports.artifact_exporter import export_artifacts
from src.decision_intel.exports.notebook_exporter import export_notebook_artifacts
from src.decision_intel.execution.plan_writer import write_execution_plan
from src.decision_intel.portfolio.aggregator import aggregate_portfolio
from src.decision_intel.portfolio.comparison import compare_portfolio
from src.decision_intel.portfolio.report_generator import generate_portfolio_report
from src.decision_intel.portfolio.summary import summarize_portfolio
from src.decision_intel.recommendations.recommendation_writer import write_recommendations
from src.decision_intel.reports.generator import generate_reports
from src.decision_intel.utils.io import ensure_run_dir, validate_run_write_path


@dataclass(frozen=True)
class AdapterResult:
    run_id: str
    manifest_path: Path


def build_decision_intel_artifacts(
    run_id: str | None = None,
    base_path: str = "runs",
    final_decision_path: str | Path | None = None,
    backtest_summary_path: str | Path | None = None,
    weights_json: str | None = None,
    weights_file: str | Path | None = None,
    date: str | None = None,
    hour: str | None = None,
    config_snapshot_path: str | None = None,
    emit_recommendations: bool = False,
) -> AdapterResult:
    base_root = Path(__file__).resolve().parents[3]
    run_id = run_id or _derive_run_id(date, hour)
    run_root = ensure_run_dir(run_id, base_path=base_path)

    final_decision_path = Path(final_decision_path) if final_decision_path else base_root / "data" / "results" / "final_decision.json"
    backtest_summary_path = Path(backtest_summary_path) if backtest_summary_path else base_root / "simulations" / "backtest_summary.json"
    if not final_decision_path.exists():
        raise ValueError(f"final_decision.json not found: {final_decision_path}")
    if not backtest_summary_path.exists():
        raise ValueError(f"backtest_summary.json not found: {backtest_summary_path}")

    if config_snapshot_path is None:
        candidate = base_root / "src" / "backtest" / "config_backtest.json"
        config_snapshot_path = str(candidate) if candidate.exists() else "unknown"

    manifest_path = validate_run_write_path(
        run_id,
        run_root / "manifests" / f"run_manifest.v{CURRENT_SCHEMA_VERSION}.json",
        base_path=base_path,
    )
    manifest = _load_or_initialize_manifest(run_id, manifest_path, config_snapshot_path)

    try:
        _update_status(manifest, "RUNNING")
        _persist_manifest(manifest_path, manifest)

        decision_payload = json.loads(final_decision_path.read_text(encoding="utf-8"))
        asof_date = _resolve_asof_date(decision_payload, base_root, date)
        decisions, horizon = _extract_decisions(decision_payload)
        decision_path, decision_entry = write_decision_outputs(
            run_id=run_id,
            decisions=decisions,
            strategy_id="quant_trading_bot",
            variant_id=None,
            horizon=horizon,
            rule_refs={"sizing_rule": "size.fixed", "constraints": [], "filters": []},
            config_snapshot_path=config_snapshot_path,
            asof_date=asof_date,
            base_path=base_path,
        )
        decision_entry = _relative_entry(decision_entry, run_root)

        metrics_payload = json.loads(backtest_summary_path.read_text(encoding="utf-8"))
        if not isinstance(metrics_payload, dict):
            raise ValueError("backtest_summary.json must be a JSON object")
        eval_path, eval_entry = write_evaluation_metrics(
            run_id=run_id,
            strategy_id="quant_trading_bot",
            variant_id=None,
            horizon=horizon,
            metrics=metrics_payload,
            base_path=base_path,
        )
        eval_entry = _relative_entry(eval_entry, run_root)

        manifest.setdefault("artifact_index", [])
        _upsert_artifact(manifest["artifact_index"], decision_entry)
        _upsert_artifact(manifest["artifact_index"], eval_entry)
        _normalize_manifest_paths(manifest)
        _persist_manifest(manifest_path, manifest)

        if emit_recommendations:
            rec_path, rec_entry = write_recommendations(
                run_id=run_id,
                base_path=base_path,
                execution_date=date,
                execution_hour=hour,
            )
            _upsert_artifact(manifest["artifact_index"], rec_entry)
            plan_path, plan_entry = write_execution_plan(
                run_id=run_id,
                recommendations_path=rec_path,
                base_path=base_path,
            )
            _upsert_artifact(manifest["artifact_index"], plan_entry)

        _update_status(manifest, "SUCCESS")
        manifest.pop("error", None)
        _normalize_manifest_paths(manifest)
        _persist_manifest(manifest_path, manifest)

        export_artifacts(run_id=run_id, base_path=base_path)
        generate_reports(run_id=run_id, base_path=base_path)
        export_notebook_artifacts(run_id=run_id, base_path=base_path)

        weights = _load_weights(weights_json, weights_file)
        if weights:
            aggregate_portfolio(run_id=run_id, weights=weights, base_path=base_path)
            summarize_portfolio(run_id=run_id, base_path=base_path)
            compare_portfolio(run_id=run_id, base_path=base_path)
            generate_portfolio_report(run_id=run_id, base_path=base_path)
        else:
            print("Portfolio weights not provided; skipping portfolio artifacts and report.")

    except Exception as exc:
        _update_status(manifest, "FAILED")
        manifest["error"] = {"error_code": "FAILED", "message": str(exc)}
        _persist_manifest(manifest_path, manifest)
        raise

    return AdapterResult(run_id=run_id, manifest_path=manifest_path)


def _derive_run_id(date: str | None, hour: str | None) -> str:
    if date and hour:
        return date.replace("-", "") + "-" + hour
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_or_initialize_manifest(run_id: str, manifest_path: Path, config_snapshot_path: str) -> Dict[str, Any]:
    if manifest_path.exists():
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "reader_min_version": MIN_READER_VERSION,
        "run_id": run_id,
        "status": "CREATED",
        "timestamps": {"created_at": _utc_now_iso()},
        "config": {"snapshot_path": config_snapshot_path},
        "data_snapshot_ids": {},
        "artifact_index": [],
        "skips": [],
    }


def _update_status(manifest: Dict[str, Any], status: str) -> None:
    timestamps = manifest.setdefault("timestamps", {})
    if status == "RUNNING" and not timestamps.get("started_at"):
        timestamps["started_at"] = _utc_now_iso()
    if status in {"SUCCESS", "FAILED", "PARTIAL", "SKIPPED"} and not timestamps.get("completed_at"):
        timestamps["completed_at"] = _utc_now_iso()
    manifest["status"] = status


def _persist_manifest(manifest_path: Path, manifest: Dict[str, Any]) -> None:
    _normalize_manifest_paths(manifest)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )


def _extract_decisions(data: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], str]:
    source = data.get("decision") if isinstance(data.get("decision"), dict) else data
    long_term = source.get("long_term", [])
    intraday = source.get("intraday", [])
    decisions: List[Dict[str, Any]] = []

    for scope, items in (("long_term", long_term), ("intraday", intraday)):
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            ticker = item.get("ticker")
            if not isinstance(ticker, str) or not ticker:
                continue
            outputs = {"decision_type": scope}
            for key in (
                "justificacion",
                "peso_pct",
                "model_score",
                "expected_return_gross_pct",
                "selection_score",
                "empirical_mean_return",
                "empirical_hit_rate",
                "empirical_observations",
            ):
                if key in item:
                    outputs[key] = item.get(key)
            decisions.append(
                {
                    "asset_id": ticker.upper().strip(),
                    "signal": 1.0,
                    "outputs": outputs,
                }
            )

    if not decisions:
        raise ValueError("final_decision.json missing expected decision keys (long_term/intraday)")

    horizon = "LONG" if long_term and not intraday else "SHORT"
    return decisions, horizon


def _relative_entry(entry: Dict[str, Any], run_root: Path) -> Dict[str, Any]:
    path = Path(entry["path"])
    run_root_abs = run_root.resolve()
    if path.is_absolute():
        entry["path"] = path.resolve().relative_to(run_root_abs).as_posix()
    else:
        entry["path"] = path.as_posix()
    return entry


def _normalize_manifest_paths(manifest: Dict[str, Any]) -> None:
    for entry in manifest.get("artifact_index", []):
        path_value = entry.get("path")
        if isinstance(path_value, str) and path_value:
            entry["path"] = Path(path_value).as_posix()


def _resolve_asof_date(data: Dict[str, Any], base_root: Path, adapter_date: str | None) -> str:
    for payload in (data, data.get("decision") if isinstance(data.get("decision"), dict) else None):
        if isinstance(payload, dict):
            asof_date = payload.get("asof_date")
            if isinstance(asof_date, str) and asof_date:
                return asof_date

    summary_path = base_root / "simulations" / "simulate_summary.json"
    if summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            asof_date = summary.get("end_date_effective") or summary.get("end_date")
            if isinstance(asof_date, str) and asof_date:
                return asof_date
        except Exception as exc:
            print(f"[WARN] No se pudo leer simulate_summary.json: {exc}")

    if adapter_date:
        print("[WARN] asof_date ausente; usando date del adapter")
        return adapter_date

    fallback = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    print("[WARN] asof_date ausente; usando fecha UTC actual")
    return fallback


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


def _load_weights(weights_json: str | None, weights_file: str | Path | None) -> Dict[str, float] | None:
    if weights_json:
        return json.loads(weights_json)
    if weights_file:
        return json.loads(Path(weights_file).read_text(encoding="utf-8"))
    return None
