"""Deterministic artifact writers for capital plans."""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any, Iterable, Mapping


def dataclass_to_dict(obj: Any) -> Any:
    """Recursively convert a dataclass (and nested dataclasses) to plain dict/list/scalar."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: dataclass_to_dict(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, Mapping):
        return {str(k): dataclass_to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [dataclass_to_dict(v) for v in obj]
    return obj


def write_json_artifact(path: Path | str, payload: Any) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = dataclass_to_dict(payload)
    with target.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    return target


def write_markdown_report(
    path: Path | str,
    title: str,
    sections: Iterable[tuple[str, str]],
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = [f"# {title}", ""]
    for heading, body in sections:
        lines.append(f"## {heading}")
        lines.append("")
        lines.append(body.rstrip())
        lines.append("")
    with target.open("w", encoding="utf-8") as fh:
        fh.write("\n".join(lines).rstrip() + "\n")
    return target


__all__ = ["dataclass_to_dict", "write_json_artifact", "write_markdown_report"]
