from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.execution.crypto_paper_artifact_recovery import (
    SUPPORTED_RECORD_KINDS,
    discover_archive_record_files,
    rebuild_cumulative_records_from_archive,
)


def _seed_archive_snapshot(
    archive_root: Path,
    *,
    stamp: str,
    filename: str,
    payload: list[dict],
) -> Path:
    target_dir = archive_root / stamp
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / filename
    target.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    return target


class CryptoPaperArtifactRecoveryTests(unittest.TestCase):
    def test_supported_record_kinds_cover_fills_orders_exit_events(self):
        self.assertIn("fills", SUPPORTED_RECORD_KINDS)
        self.assertIn("orders", SUPPORTED_RECORD_KINDS)
        self.assertIn("exit_events", SUPPORTED_RECORD_KINDS)
        self.assertEqual(
            SUPPORTED_RECORD_KINDS["fills"]["filename"], "crypto_paper_fills.json"
        )
        self.assertEqual(
            SUPPORTED_RECORD_KINDS["orders"]["filename"], "crypto_paper_orders.json"
        )
        self.assertEqual(
            SUPPORTED_RECORD_KINDS["exit_events"]["filename"],
            "crypto_paper_exit_events.json",
        )

    def test_discover_archive_record_files_returns_sorted_recursive_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_root = Path(tmp) / "archive"
            _seed_archive_snapshot(
                archive_root,
                stamp="2026-04-29/120000",
                filename="crypto_paper_fills.json",
                payload=[],
            )
            _seed_archive_snapshot(
                archive_root,
                stamp="2026-04-30/090000",
                filename="crypto_paper_fills.json",
                payload=[],
            )
            _seed_archive_snapshot(
                archive_root,
                stamp="2026-04-30/180000",
                filename="crypto_paper_orders.json",
                payload=[],
            )

            fills_paths = discover_archive_record_files(
                archive_root=archive_root, filename="crypto_paper_fills.json"
            )
            self.assertEqual(len(fills_paths), 2)
            self.assertEqual(fills_paths, sorted(fills_paths))

    def test_rebuild_recovers_distinct_fills_with_colliding_fill_ids(self):
        """Old buggy archives reused fill_id across runs. Recovery must
        deduplicate by content+timestamp, NOT by fill_id, so all distinct
        historical fills are preserved.
        """

        with tempfile.TemporaryDirectory() as tmp:
            archive_root = Path(tmp) / "archive"
            day1 = [
                {
                    "fill_id": "crypto-paper-fill-0001",
                    "order_id": "crypto-paper-order-0001",
                    "symbol": "BTCUSDT",
                    "side": "BUY",
                    "quantity": 0.001,
                    "fill_price": 76000.0,
                    "gross_notional": 76.0,
                    "fee": 0.025,
                    "slippage": 0.0,
                    "net_notional": 76.025,
                    "filled_at": "2026-04-28T12:00:00",
                    "metadata": {},
                }
            ]
            day2 = [
                {
                    "fill_id": "crypto-paper-fill-0001",
                    "order_id": "crypto-paper-order-0001",
                    "symbol": "BTCUSDT",
                    "side": "BUY",
                    "quantity": 0.001,
                    "fill_price": 77000.0,
                    "gross_notional": 77.0,
                    "fee": 0.025,
                    "slippage": 0.0,
                    "net_notional": 77.025,
                    "filled_at": "2026-04-29T12:00:00",
                    "metadata": {},
                }
            ]
            day3 = [
                {
                    "fill_id": "crypto-paper-fill-0001",
                    "order_id": "crypto-paper-order-0001",
                    "symbol": "BTCUSDT",
                    "side": "BUY",
                    "quantity": 0.001,
                    "fill_price": 78000.0,
                    "gross_notional": 78.0,
                    "fee": 0.025,
                    "slippage": 0.0,
                    "net_notional": 78.025,
                    "filled_at": "2026-04-30T12:00:00",
                    "metadata": {},
                }
            ]
            _seed_archive_snapshot(archive_root, stamp="2026-04-28/120000", filename="crypto_paper_fills.json", payload=day1)
            _seed_archive_snapshot(archive_root, stamp="2026-04-29/120000", filename="crypto_paper_fills.json", payload=day2)
            _seed_archive_snapshot(archive_root, stamp="2026-04-30/120000", filename="crypto_paper_fills.json", payload=day3)

            output_path = Path(tmp) / "rebuilt" / "crypto_paper_fills.json"
            rebuilt, warnings = rebuild_cumulative_records_from_archive(
                archive_root=archive_root,
                record_kind="fills",
                output_path=output_path,
            )
            self.assertEqual(len(rebuilt), 3, f"expected 3 distinct fills, got {rebuilt}")
            filled_ats = [item["filled_at"] for item in rebuilt]
            self.assertEqual(filled_ats, sorted(filled_ats))
            self.assertEqual(warnings, [])
            self.assertTrue(output_path.is_file())
            persisted = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(len(persisted), 3)

    def test_rebuild_deduplicates_genuinely_identical_records_across_archives(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_root = Path(tmp) / "archive"
            duplicate = [
                {
                    "fill_id": "crypto-paper-fill-0001",
                    "order_id": "crypto-paper-order-0001",
                    "symbol": "BTCUSDT",
                    "side": "BUY",
                    "quantity": 0.001,
                    "fill_price": 76000.0,
                    "gross_notional": 76.0,
                    "fee": 0.025,
                    "slippage": 0.0,
                    "net_notional": 76.025,
                    "filled_at": "2026-04-28T12:00:00",
                    "metadata": {},
                }
            ]
            _seed_archive_snapshot(archive_root, stamp="2026-04-28/120000", filename="crypto_paper_fills.json", payload=duplicate)
            _seed_archive_snapshot(archive_root, stamp="2026-04-28/130000", filename="crypto_paper_fills.json", payload=duplicate)

            rebuilt, _ = rebuild_cumulative_records_from_archive(
                archive_root=archive_root,
                record_kind="fills",
            )
            self.assertEqual(len(rebuilt), 1)

    def test_rebuild_returns_warning_when_no_archive_snapshots_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive_root = Path(tmp) / "archive"
            archive_root.mkdir(parents=True, exist_ok=True)
            rebuilt, warnings = rebuild_cumulative_records_from_archive(
                archive_root=archive_root, record_kind="fills"
            )
            self.assertEqual(rebuilt, [])
            self.assertTrue(any("no_archive_snapshots_found" in w for w in warnings))

    def test_rebuild_rejects_unknown_record_kind(self):
        with self.assertRaises(ValueError):
            rebuild_cumulative_records_from_archive(
                archive_root="/nonexistent",
                record_kind="not_a_kind",
            )

    def test_rebuild_does_not_invent_records_for_missing_archive_root(self):
        rebuilt, warnings = rebuild_cumulative_records_from_archive(
            archive_root="/this/path/should/not/exist",
            record_kind="fills",
        )
        self.assertEqual(rebuilt, [])
        self.assertTrue(any("no_archive_snapshots_found" in w for w in warnings))


if __name__ == "__main__":
    unittest.main()
