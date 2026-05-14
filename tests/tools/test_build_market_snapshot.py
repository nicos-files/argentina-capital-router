"""Tests for src/tools/build_market_snapshot.py.

Manual review only. No live trading. No broker automation.
No network. No API keys. No paid data sources.
"""
from __future__ import annotations

import io
import json
import socket
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

from src.market_data.manual_snapshot import load_manual_market_snapshot
from src.tools import build_market_snapshot as cli


class _NetworkBlocker:
    """Fail any test that accidentally opens a socket."""

    def __enter__(self) -> "_NetworkBlocker":
        self._orig = socket.socket

        def _blocked(*args: Any, **kwargs: Any) -> Any:
            raise AssertionError(
                "network access is forbidden in build_market_snapshot tests"
            )

        socket.socket = _blocked  # type: ignore[assignment]
        return self

    def __exit__(self, *exc_info: Any) -> None:
        socket.socket = self._orig  # type: ignore[assignment]


def _run(args: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(args)
    return rc, buf.getvalue()


class BuildMarketSnapshotCliTests(unittest.TestCase):
    def test_static_example_writes_round_trippable_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir, _NetworkBlocker():
            out = Path(tmp_dir) / "market" / "2026-05-12.json"
            rc, output = _run(
                [
                    "--date",
                    "2026-05-12",
                    "--provider",
                    "static-example",
                    "--usdars-mep",
                    "1200",
                    "--usdars-ccl",
                    "1220",
                    "--usdars-official",
                    "1000",
                    "--money-market-monthly-pct",
                    "2.5",
                    "--caucion-monthly-pct",
                    "2.8",
                    "--expected-fx-devaluation-monthly-pct",
                    "1.5",
                    "--out",
                    str(out),
                ]
            )
            self.assertEqual(rc, 0, msg=output)
            self.assertTrue(out.exists())

            # The output must be loadable by the existing manual snapshot
            # loader (which enforces manual_review_only=true / no live
            # trading).
            snapshot = load_manual_market_snapshot(out)
            self.assertTrue(snapshot.manual_review_only)
            self.assertFalse(snapshot.live_trading_enabled)
            self.assertEqual(snapshot.as_of, "2026-05-12")
            self.assertEqual(snapshot.completeness, "complete")
            self.assertGreaterEqual(len(snapshot.quotes), 10)
            self.assertIn("USDARS_MEP", snapshot.fx_rates)
            self.assertEqual(snapshot.fx_rates["USDARS_MEP"].rate, 1200.0)
            self.assertEqual(
                snapshot.rates["money_market_monthly_pct"].value, 2.5
            )

    def test_default_out_path_under_repo_snapshots_market(self) -> None:
        """When --out is omitted, the path defaults to
        snapshots/market/<date>.json under the repo root."""
        with tempfile.TemporaryDirectory() as tmp_dir, _NetworkBlocker():
            # Use an explicit --out anyway so the test never touches the
            # real repository tree; we just check the parser builds a path
            # via _resolve_output_path.
            out = Path(tmp_dir) / "snapshots" / "market" / "2099-01-02.json"
            rc, _ = _run(
                [
                    "--date",
                    "2099-01-02",
                    "--provider",
                    "static-example",
                    "--usdars-mep",
                    "1500",
                    "--out",
                    str(out),
                ]
            )
            self.assertEqual(rc, 0)
            self.assertTrue(out.exists())

    def test_refuses_overwrite_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir, _NetworkBlocker():
            out = Path(tmp_dir) / "m.json"
            out.write_text('{"sentinel": true}', encoding="utf-8")
            rc, output = _run(
                [
                    "--date",
                    "2026-05-12",
                    "--provider",
                    "static-example",
                    "--out",
                    str(out),
                ]
            )
            self.assertEqual(rc, 1, msg=output)
            self.assertIn("output file already exists", output)
            # The sentinel file must not have been clobbered.
            self.assertEqual(
                out.read_text(encoding="utf-8"), '{"sentinel": true}'
            )

    def test_overwrite_flag_replaces_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir, _NetworkBlocker():
            out = Path(tmp_dir) / "m.json"
            out.write_text("PLACEHOLDER", encoding="utf-8")
            rc, _ = _run(
                [
                    "--date",
                    "2026-05-12",
                    "--provider",
                    "static-example",
                    "--out",
                    str(out),
                    "--overwrite",
                ]
            )
            self.assertEqual(rc, 0)
            snapshot = load_manual_market_snapshot(out)
            self.assertEqual(snapshot.as_of, "2026-05-12")

    def test_json_summary_is_parseable_and_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir, _NetworkBlocker():
            out = Path(tmp_dir) / "m.json"
            rc, output = _run(
                [
                    "--date",
                    "2026-05-12",
                    "--provider",
                    "static-example",
                    "--usdars-mep",
                    "1200",
                    "--out",
                    str(out),
                    "--json",
                ]
            )
            self.assertEqual(rc, 0, msg=output)
            payload = json.loads(output)
            self.assertEqual(payload["status"], "ok")
            self.assertTrue(payload["manual_review_only"])
            self.assertFalse(payload["live_trading_enabled"])
            self.assertEqual(payload["provider"], "static-example")
            self.assertEqual(payload["snapshot_path"], str(out))
            self.assertGreater(payload["quotes_requested"], 0)
            self.assertEqual(
                payload["quotes_loaded"], payload["quotes_requested"]
            )
            # No API keys / secrets must leak into the summary or warnings.
            # The benign metadata field ``requires_api_key`` is allowed.
            blob = json.dumps(payload).lower()
            for forbidden in (
                '"api_key"',
                '"apikey"',
                '"secret"',
                '"token"',
            ):
                self.assertNotIn(forbidden, blob)
            # provider_health must report offline + keyless.
            for h in payload["provider_health"]:
                self.assertFalse(h["network_required"])
                self.assertFalse(h["requires_api_key"])

    def test_does_not_emit_forbidden_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir, _NetworkBlocker():
            tmp = Path(tmp_dir)
            out = tmp / "market" / "2026-05-12.json"
            rc, _ = _run(
                [
                    "--date",
                    "2026-05-12",
                    "--provider",
                    "static-example",
                    "--usdars-mep",
                    "1200",
                    "--out",
                    str(out),
                ]
            )
            self.assertEqual(rc, 0)
            forbidden = list(tmp.rglob("execution.plan")) + list(
                tmp.rglob("final_decision.json")
            )
            self.assertEqual(forbidden, [])

    def test_no_network_during_run(self) -> None:
        # Explicit second-layer guard in case _NetworkBlocker is bypassed.
        with tempfile.TemporaryDirectory() as tmp_dir, _NetworkBlocker():
            out = Path(tmp_dir) / "m.json"
            rc, _ = _run(
                [
                    "--date",
                    "2026-05-12",
                    "--provider",
                    "static-example",
                    "--usdars-mep",
                    "1200",
                    "--out",
                    str(out),
                ]
            )
            self.assertEqual(rc, 0)

    def test_invalid_universe_path_returns_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir, _NetworkBlocker():
            rc, output = _run(
                [
                    "--date",
                    "2026-05-12",
                    "--provider",
                    "static-example",
                    "--universe",
                    "/does/not/exist.json",
                    "--out",
                    str(Path(tmp_dir) / "m.json"),
                    "--json",
                ]
            )
            self.assertEqual(rc, 1)
            payload = json.loads(output)
            self.assertEqual(payload["status"], "universe_failed")

    def test_negative_fx_rate_returns_usage_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir, _NetworkBlocker():
            rc, output = _run(
                [
                    "--date",
                    "2026-05-12",
                    "--provider",
                    "static-example",
                    "--usdars-mep",
                    "-1",
                    "--out",
                    str(Path(tmp_dir) / "m.json"),
                    "--json",
                ]
            )
            self.assertEqual(rc, 2)
            payload = json.loads(output)
            self.assertEqual(payload["status"], "usage_error")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
