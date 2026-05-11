from __future__ import annotations

from pathlib import Path


def _validate_run_id(run_id: str) -> None:
    if not run_id or "/" in run_id or "\\" in run_id:
        raise ValueError("run_id must be a single path segment")


def ensure_run_dir(run_id: str, base_path: str = "runs") -> Path:
    """
    Create the run directory spine idempotently and return the run root path.
    """
    _validate_run_id(run_id)
    base = Path(base_path)
    run_root = base / run_id
    for subdir in ("manifests", "logs", "artifacts", "reports"):
        (run_root / subdir).mkdir(parents=True, exist_ok=True)
    return run_root


def validate_run_write_path(run_id: str, target_path: str | Path, base_path: str = "runs") -> Path:
    """
    Validate that a target write path stays under runs/{run_id} and return the resolved path.
    """
    _validate_run_id(run_id)
    base = Path(base_path)
    run_root = (base / run_id).resolve()
    candidate = Path(target_path).resolve()
    if run_root not in candidate.parents and candidate != run_root:
        raise ValueError(f"target_path must be under {run_root}")
    return candidate
