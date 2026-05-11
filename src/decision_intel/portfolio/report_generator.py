from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Dict, Tuple

from src.decision_intel.contracts.metadata_models import CURRENT_SCHEMA_VERSION, MIN_READER_VERSION
from src.decision_intel.utils.io import ensure_run_dir


def generate_portfolio_report(run_id: str, base_path: str = "runs") -> Tuple[Path, Path]:
    run_root = ensure_run_dir(run_id, base_path=base_path)
    manifest_path = run_root / "manifests" / f"run_manifest.v{CURRENT_SCHEMA_VERSION}.json"
    manifest = _load_manifest(manifest_path, run_id)

    aggregation_payload, aggregation_path = _load_artifact_payload(run_root, manifest, "portfolio.aggregation")
    summary_payload, summary_path = _load_artifact_payload(run_root, manifest, "portfolio.summary")
    comparison_payload, comparison_path = _load_artifact_payload(run_root, manifest, "portfolio.comparison")

    markdown = _build_markdown(
        manifest,
        aggregation_payload,
        aggregation_path,
        summary_payload,
        summary_path,
        comparison_payload,
        comparison_path,
    )
    html_report = _build_html(
        manifest,
        aggregation_payload,
        aggregation_path,
        summary_payload,
        summary_path,
        comparison_payload,
        comparison_path,
    )

    reports_dir = run_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    md_path = reports_dir / "portfolio_report.md"
    html_path = reports_dir / "portfolio_report.html"
    md_path.write_text(markdown, encoding="utf-8")
    html_path.write_text(html_report, encoding="utf-8")
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
    aggregation_payload: Dict[str, Any] | None,
    aggregation_path: str | None,
    summary_payload: Dict[str, Any] | None,
    summary_path: str | None,
    comparison_payload: Dict[str, Any] | None,
    comparison_path: str | None,
) -> str:
    lines = ["# Portfolio Report", ""]
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

    lines.append("## portfolio.aggregation")
    if aggregation_payload and aggregation_path:
        lines.append(f"- source: {aggregation_path}")
        lines.append(f"- total_weight: {aggregation_payload.get('total_weight')}")
        lines.append(f"- total_weighted_signal: {aggregation_payload.get('total_weighted_signal')}")
        lines.append(f"- missing_weights: {aggregation_payload.get('missing_weights', [])}")
        lines.append("")
        lines.append("| asset_id | signal | weight | weighted_signal |")
        lines.append("| --- | --- | --- | --- |")
        positions = aggregation_payload.get("positions", [])
        for position in sorted(positions, key=lambda row: row.get("asset_id", "")):
            lines.append(
                f"| {position.get('asset_id')} | {position.get('signal')} | {position.get('weight')} | {position.get('weighted_signal')} |"
            )
    else:
        lines.append("- source: not available")
    lines.append("")

    lines.append("## portfolio.summary")
    if summary_payload and summary_path:
        lines.append(f"- source: {summary_path}")
        lines.append(f"- number_of_assets: {summary_payload.get('number_of_assets')}")
        lines.append(f"- total_weight: {summary_payload.get('total_weight')}")
        lines.append(f"- total_weighted_signal: {summary_payload.get('total_weighted_signal')}")
        lines.append(f"- count_missing_weights: {summary_payload.get('count_missing_weights')}")
    else:
        lines.append("- source: not available")
    lines.append("")

    lines.append("## portfolio.comparison")
    if comparison_payload and comparison_path:
        lines.append(f"- source: {comparison_path}")
        lines.append(f"- missing_in_weights: {comparison_payload.get('missing_in_weights', [])}")
        lines.append(f"- missing_in_decisions: {comparison_payload.get('missing_in_decisions', [])}")
        lines.append("")
        lines.append("| asset_id | signal | weight | weighted_signal | delta_weighted_signal |")
        lines.append("| --- | --- | --- | --- | --- |")
        rows = comparison_payload.get("by_asset", [])
        for row in sorted(rows, key=lambda item: item.get("asset_id", "")):
            lines.append(
                f"| {row.get('asset_id')} | {row.get('signal')} | {row.get('weight')} | {row.get('weighted_signal')} | {row.get('delta_weighted_signal')} |"
            )
    else:
        lines.append("- source: not available")
    lines.append("")
    return "\n".join(lines)


def _build_html(
    manifest: Dict[str, Any],
    aggregation_payload: Dict[str, Any] | None,
    aggregation_path: str | None,
    summary_payload: Dict[str, Any] | None,
    summary_path: str | None,
    comparison_payload: Dict[str, Any] | None,
    comparison_path: str | None,
) -> str:
    parts = [
        "<html><head><meta charset='utf-8'><title>Portfolio Report</title></head><body>",
        "<h1>Portfolio Report</h1>",
        "<h2>Metadata</h2>",
        "<ul>",
    ]
    metadata = {
        "run_id": manifest.get("run_id"),
        "status": manifest.get("status"),
        "created_at": manifest.get("timestamps", {}).get("created_at"),
        "started_at": manifest.get("timestamps", {}).get("started_at"),
        "completed_at": manifest.get("timestamps", {}).get("completed_at"),
        "config_snapshot_path": manifest.get("config", {}).get("snapshot_path"),
    }
    for key in sorted(metadata.keys()):
        parts.append(f"<li>{html.escape(str(key))}: {html.escape(str(metadata[key]))}</li>")
    parts.append("</ul>")

    parts.append("<h2>portfolio.aggregation</h2>")
    if aggregation_payload and aggregation_path:
        parts.append(f"<p>source: {html.escape(aggregation_path)}</p>")
        parts.append(f"<p>total_weight: {html.escape(str(aggregation_payload.get('total_weight')))}</p>")
        parts.append(f"<p>total_weighted_signal: {html.escape(str(aggregation_payload.get('total_weighted_signal')))}</p>")
        parts.append(f"<p>missing_weights: {html.escape(str(aggregation_payload.get('missing_weights', [])))}</p>")
        parts.append("<table><thead><tr><th>asset_id</th><th>signal</th><th>weight</th><th>weighted_signal</th></tr></thead><tbody>")
        positions = aggregation_payload.get("positions", [])
        for position in sorted(positions, key=lambda row: row.get("asset_id", "")):
            parts.append(
                "<tr>"
                f"<td>{html.escape(str(position.get('asset_id')))}</td>"
                f"<td>{html.escape(str(position.get('signal')))}</td>"
                f"<td>{html.escape(str(position.get('weight')))}</td>"
                f"<td>{html.escape(str(position.get('weighted_signal')))}</td>"
                "</tr>"
            )
        parts.append("</tbody></table>")
    else:
        parts.append("<p>source: not available</p>")

    parts.append("<h2>portfolio.summary</h2>")
    if summary_payload and summary_path:
        parts.append(f"<p>source: {html.escape(summary_path)}</p>")
        parts.append(f"<p>number_of_assets: {html.escape(str(summary_payload.get('number_of_assets')))}</p>")
        parts.append(f"<p>total_weight: {html.escape(str(summary_payload.get('total_weight')))}</p>")
        parts.append(f"<p>total_weighted_signal: {html.escape(str(summary_payload.get('total_weighted_signal')))}</p>")
        parts.append(f"<p>count_missing_weights: {html.escape(str(summary_payload.get('count_missing_weights')))}</p>")
    else:
        parts.append("<p>source: not available</p>")

    parts.append("<h2>portfolio.comparison</h2>")
    if comparison_payload and comparison_path:
        parts.append(f"<p>source: {html.escape(comparison_path)}</p>")
        parts.append(f"<p>missing_in_weights: {html.escape(str(comparison_payload.get('missing_in_weights', [])))}</p>")
        parts.append(f"<p>missing_in_decisions: {html.escape(str(comparison_payload.get('missing_in_decisions', [])))}</p>")
        parts.append("<table><thead><tr><th>asset_id</th><th>signal</th><th>weight</th><th>weighted_signal</th><th>delta_weighted_signal</th></tr></thead><tbody>")
        rows = comparison_payload.get("by_asset", [])
        for row in sorted(rows, key=lambda item: item.get("asset_id", "")):
            parts.append(
                "<tr>"
                f"<td>{html.escape(str(row.get('asset_id')))}</td>"
                f"<td>{html.escape(str(row.get('signal')))}</td>"
                f"<td>{html.escape(str(row.get('weight')))}</td>"
                f"<td>{html.escape(str(row.get('weighted_signal')))}</td>"
                f"<td>{html.escape(str(row.get('delta_weighted_signal')))}</td>"
                "</tr>"
            )
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
