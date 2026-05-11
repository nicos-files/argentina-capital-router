"""Recovery helpers for crypto paper cumulative artifacts.

These helpers scan archived per-run snapshots written by
``scripts/run_crypto_paper_forward_daily.py`` and rebuild a cumulative
records file by **content+timestamp** uniqueness, deliberately ignoring the
``fill_id`` / ``order_id`` / ``exit_id`` fields. This is the recovery path
when a previous bug caused id collisions across runs to silently overwrite
historical records.

The helpers do NOT:

- invent fake fills, orders, or exits;
- contact any broker, exchange, or live API;
- mutate canonical state files (positions/snapshot);
- modify ``execution.plan`` or ``final_decision.json`` artifacts;
- modify the production ``config/market_universe/crypto.json``.

They only read JSON snapshots from disk and write a deduplicated cumulative
JSON list to a target path.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


SUPPORTED_RECORD_KINDS: dict[str, dict[str, str]] = {
    "fills": {"filename": "crypto_paper_fills.json", "timestamp_key": "filled_at"},
    "orders": {"filename": "crypto_paper_orders.json", "timestamp_key": "created_at"},
    "exit_events": {"filename": "crypto_paper_exit_events.json", "timestamp_key": "exited_at"},
}


def _load_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8").strip()
    except Exception:
        return []
    if not text:
        return []
    try:
        payload = json.loads(text)
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _identity_signature(record: dict[str, Any], *, exclude_keys: tuple[str, ...]) -> str:
    """Build a stable content signature ignoring ``exclude_keys`` (e.g. id fields)."""

    filtered = {key: value for key, value in record.items() if key not in exclude_keys}
    try:
        return json.dumps(filtered, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        return repr(filtered)


def discover_archive_record_files(
    *,
    archive_root: str | Path,
    filename: str,
) -> list[Path]:
    """Return all ``filename`` files under ``archive_root`` recursively, sorted.

    The wrapper writes archive directories as ``YYYY-MM-DD/HHMMSS/<artifacts>``
    so a recursive glob captures every snapshot deterministically.
    """

    root = Path(archive_root)
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob(filename) if p.is_file())


def rebuild_cumulative_records_from_archive(
    *,
    archive_root: str | Path,
    record_kind: str,
    output_path: str | Path | None = None,
    id_keys: tuple[str, ...] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Rebuild a cumulative records list by content+timestamp uniqueness.

    Args:
        archive_root: Directory containing per-run archive snapshots.
        record_kind: One of ``"fills"``, ``"orders"``, ``"exit_events"``.
        output_path: Optional path to write the rebuilt cumulative list.
        id_keys: Field names to ignore when computing the content signature.
            Defaults to ``("fill_id",)``, ``("order_id",)``, or
            ``("exit_id",)`` depending on ``record_kind``.

    Returns:
        ``(records, warnings)`` where ``records`` is the deduplicated list
        sorted by the kind's timestamp key (then by content for stability).
    """

    if record_kind not in SUPPORTED_RECORD_KINDS:
        raise ValueError(
            f"Unsupported record_kind={record_kind!r}; "
            f"expected one of {sorted(SUPPORTED_RECORD_KINDS.keys())}"
        )
    spec = SUPPORTED_RECORD_KINDS[record_kind]
    filename = spec["filename"]
    timestamp_key = spec["timestamp_key"]
    default_id_keys = {
        "fills": ("fill_id",),
        "orders": ("order_id",),
        "exit_events": ("exit_id",),
    }
    exclude_keys = id_keys if id_keys is not None else default_id_keys[record_kind]

    snapshot_paths = discover_archive_record_files(archive_root=archive_root, filename=filename)
    warnings: list[str] = []
    seen_signatures: set[str] = set()
    rebuilt: list[dict[str, Any]] = []
    for snapshot_path in snapshot_paths:
        records = _load_records(snapshot_path)
        if not records:
            continue
        for record in records:
            signature = _identity_signature(record, exclude_keys=exclude_keys)
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            rebuilt.append(record)

    def _content_key(record: dict[str, Any]) -> str:
        try:
            return json.dumps(record, sort_keys=True, ensure_ascii=False, default=str)
        except Exception:
            return repr(record)

    def _sort_key(record: dict[str, Any]) -> tuple:
        timestamp_value = record.get(timestamp_key)
        primary = "" if timestamp_value is None else str(timestamp_value)
        return (primary, _content_key(record))

    rebuilt.sort(key=_sort_key)

    if output_path is not None:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(rebuilt, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
            encoding="utf-8",
        )

    if not snapshot_paths:
        warnings.append(
            f"no_archive_snapshots_found:{record_kind}:{archive_root}"
        )
    return rebuilt, warnings
