from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Dict, Tuple

from src.decision_intel.contracts.decisions.decision_constants import DECISION_ARTIFACT_NAME
from src.decision_intel.contracts.evaluation.metrics_constants import EVAL_ARTIFACT_NAME
from src.decision_intel.contracts.metadata_models import CURRENT_SCHEMA_VERSION, MIN_READER_VERSION
from src.decision_intel.utils.io import ensure_run_dir


def generate_reports(run_id: str, base_path: str = "runs") -> Tuple[Path, Path]:
    run_root = ensure_run_dir(run_id, base_path=base_path)
    manifest_path = run_root / "manifests" / f"run_manifest.v{CURRENT_SCHEMA_VERSION}.json"
    manifest = _load_manifest(manifest_path, run_id)

    decision_payload, decision_path = _load_artifact_payload(run_root, manifest, DECISION_ARTIFACT_NAME)
    metrics_payload, metrics_path = _load_artifact_payload(run_root, manifest, EVAL_ARTIFACT_NAME)

    markdown = _build_markdown(manifest, decision_payload, decision_path, metrics_payload, metrics_path)
    html = _build_html(manifest, decision_payload, decision_path, metrics_payload, metrics_path)

    reports_dir = run_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    md_path = reports_dir / "run_report.md"
    html_path = reports_dir / "run_report.html"
    md_path.write_text(markdown, encoding="utf-8")
    html_path.write_text(html, encoding="utf-8")
    return md_path, html_path


def _load_manifest(path: Path, run_id: str) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("manifest must be a JSON object")
    if data.get("schema_version") != CURRENT_SCHEMA_VERSION:
        raise ValueError("manifest schema_version mismatch")
    if not _version_allows_reader(data.get("reader_min_version")):
        raise ValueError("manifest reader_min_version not supported")
    if data.get("run_id") != run_id:
        raise ValueError("manifest run_id does not match")
    return data


def _load_artifact_payload(
    run_root: Path,
    manifest: Dict[str, Any],
    name: str,
) -> Tuple[Dict[str, Any] | None, str | None]:
    for entry in manifest.get("artifact_index", []):
        if entry.get("name") == name:
            path_value = entry.get("path")
            if not path_value:
                return None, None
            path = _resolve_manifest_path(run_root, path_value)
            return json.loads(Path(path).read_text(encoding="utf-8")), path
    return None, None


def _resolve_manifest_path(run_root: Path, value: str) -> str:
    path = Path(value)
    if path.is_absolute():
        return str(path)
    return str(run_root / path)


def _build_markdown(
    manifest: Dict[str, Any],
    decision_payload: Dict[str, Any] | None,
    decision_path: str | None,
    metrics_payload: Dict[str, Any] | None,
    metrics_path: str | None,
) -> str:
    lines = ["# Run Report", ""]
    lines.append("## Metadata")
    lines.append(f"- run_id: {manifest.get('run_id')}")
    lines.append(f"- status: {manifest.get('status')}")
    timestamps = manifest.get("timestamps", {})
    lines.append(f"- created_at: {timestamps.get('created_at')}")
    lines.append(f"- started_at: {timestamps.get('started_at')}")
    lines.append(f"- completed_at: {timestamps.get('completed_at')}")
    config = manifest.get("config", {})
    lines.append(f"- config_snapshot_path: {config.get('snapshot_path')}")
    lines.append("")

    lines.append(f"## {DECISION_ARTIFACT_NAME}")
    if decision_payload and decision_path:
        lines.append(f"- source: {decision_path}")
        lines.append(f"- strategy_id: {decision_payload.get('strategy_id')}")
        lines.append(f"- horizon: {decision_payload.get('horizon')}")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(decision_payload.get("decisions", []), sort_keys=True, indent=2))
        lines.append("```")
    else:
        lines.append("- source: not available")
    lines.append("")

    lines.append(f"## {EVAL_ARTIFACT_NAME}")
    if metrics_payload and metrics_path:
        lines.append(f"- source: {metrics_path}")
        lines.append(f"- strategy_id: {metrics_payload.get('strategy_id')}")
        lines.append(f"- horizon: {metrics_payload.get('horizon')}")
        lines.append("")
        lines.append("| metric | value |")
        lines.append("| --- | --- |")
        metrics = metrics_payload.get("metrics", {})
        for key in sorted(metrics.keys()):
            lines.append(f"| {key} | {metrics[key]} |")
    else:
        lines.append("- source: not available")
    lines.append("")
    return "\n".join(lines)


def _build_html(
    manifest: Dict[str, Any],
    decision_payload: Dict[str, Any] | None,
    decision_path: str | None,
    metrics_payload: Dict[str, Any] | None,
    metrics_path: str | None,
) -> str:
    metadata = {
        "run_id": manifest.get("run_id"),
        "status": manifest.get("status"),
        "created_at": manifest.get("timestamps", {}).get("created_at"),
        "started_at": manifest.get("timestamps", {}).get("started_at"),
        "completed_at": manifest.get("timestamps", {}).get("completed_at"),
        "config_snapshot_path": manifest.get("config", {}).get("snapshot_path"),
    }
    parts = [
        "<html><head><meta charset='utf-8'><title>Run Report</title></head><body>",
        "<h1>Run Report</h1>",
        "<h2>Metadata</h2>",
        "<ul>",
    ]
    for key in sorted(metadata.keys()):
        parts.append(f"<li>{key}: {metadata[key]}</li>")
    parts.append("</ul>")

    parts.append(f"<h2>{html.escape(DECISION_ARTIFACT_NAME)}</h2>")
    if decision_payload and decision_path:
        parts.append(f"<p>source: {html.escape(decision_path)}</p>")
        parts.append(f"<p>strategy_id: {html.escape(str(decision_payload.get('strategy_id')))}</p>")
        parts.append(f"<p>horizon: {html.escape(str(decision_payload.get('horizon')))}</p>")
        parts.append("<pre>")
        parts.append(
            html.escape(json.dumps(decision_payload.get("decisions", []), sort_keys=True, indent=2))
        )
        parts.append("</pre>")
    else:
        parts.append("<p>source: not available</p>")

    parts.append(f"<h2>{html.escape(EVAL_ARTIFACT_NAME)}</h2>")
    if metrics_payload and metrics_path:
        parts.append(f"<p>source: {html.escape(metrics_path)}</p>")
        parts.append(f"<p>strategy_id: {html.escape(str(metrics_payload.get('strategy_id')))}</p>")
        parts.append(f"<p>horizon: {html.escape(str(metrics_payload.get('horizon')))}</p>")
        parts.append("<table><thead><tr><th>metric</th><th>value</th></tr></thead><tbody>")
        metrics = metrics_payload.get("metrics", {})
        for key in sorted(metrics.keys()):
            parts.append(f"<tr><td>{html.escape(str(key))}</td><td>{html.escape(str(metrics[key]))}</td></tr>")
        parts.append("</tbody></table>")
    else:
        parts.append("<p>source: not available</p>")

    parts.append("</body></html>")
    return "\n".join(parts)


def _version_allows_reader(reader_min_version: str | None) -> bool:
    if not reader_min_version:
        return False
    parsed_reader = _parse_version(reader_min_version)
    if parsed_reader is None:
        return False
    parsed_current = _parse_version(MIN_READER_VERSION)
    if parsed_current is None:
        return False
    return parsed_reader <= parsed_current


def _parse_version(value: str) -> tuple[int, ...] | None:
    try:
        return tuple(int(part) for part in value.split("."))
    except ValueError:
        return None
