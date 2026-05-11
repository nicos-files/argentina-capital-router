"""Tests for the ``run_binance_testnet_execution`` CLI wrapper.

The CLI must:

- exit non-zero when the executor refuses (env not set, base URL invalid, etc.),
- exit zero when the executor runs successfully, even with no actionable events,
- emit a JSON audit line to stdout that does not leak secrets,
- never call live Binance hosts (we patch the executor to a fake to assert this).
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.tools import run_binance_testnet_execution as cli


class CLIArgParsingTests(unittest.TestCase):
    def test_parser_requires_paper_artifacts_dir(self) -> None:
        parser = cli.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args([])

    def test_parser_accepts_dry_run_and_rebuild_flags(self) -> None:
        parser = cli.build_parser()
        args = parser.parse_args(
            [
                "--paper-artifacts-dir",
                "/tmp/x",
                "--testnet-artifacts-dir",
                "/tmp/y",
                "--rebuild-semantic",
                "--dry-run",
            ]
        )
        self.assertEqual(args.paper_artifacts_dir, "/tmp/x")
        self.assertEqual(args.testnet_artifacts_dir, "/tmp/y")
        self.assertTrue(args.rebuild_semantic)
        self.assertTrue(args.dry_run)


class CLIExitCodeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.paper_dir = Path(self._tmp.name) / "crypto_paper"
        self.paper_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run_with_fake_executor(
        self, return_value: dict[str, Any]
    ) -> tuple[int, dict[str, Any]]:
        buf = io.StringIO()
        with mock.patch.object(
            cli, "run_binance_testnet_execution", return_value=return_value
        ) as patched, redirect_stdout(buf):
            code = cli.main(["--paper-artifacts-dir", str(self.paper_dir)])
        # The CLI should NEVER read the real env or talk to Binance: the
        # executor it calls is patched, so we only assert it was called once.
        self.assertEqual(patched.call_count, 1)
        try:
            audit = json.loads(buf.getvalue().strip().splitlines()[-1])
        except Exception:
            audit = {}
        return code, audit

    def test_exit_zero_on_ok_true(self) -> None:
        code, audit = self._run_with_fake_executor(
            {
                "ok": True,
                "testnet": True,
                "live_trading": False,
                "dry_run": False,
                "order_test_only": True,
                "base_url": "https://testnet.binance.vision",
                "max_notional": 25.0,
                "allowed_symbols": ["BTCUSDT", "ETHUSDT"],
                "considered_count": 2,
                "placed_count": 0,
                "test_ok_count": 2,
                "rejected_count": 0,
                "skipped_count": 0,
                "warnings": [],
                "api_key_masked": "****abcd",
                "testnet_artifacts_dir": "/tmp/crypto_testnet",
            }
        )
        self.assertEqual(code, 0)
        self.assertTrue(audit["ok"])
        self.assertTrue(audit["testnet"])
        self.assertFalse(audit["live_trading"])
        self.assertEqual(audit["test_ok_count"], 2)
        self.assertIn("env_flags", audit)
        # The audit envelope must reference the gating env vars by name.
        self.assertIn("ENABLE_BINANCE_TESTNET_EXECUTION", audit["env_flags"])
        self.assertIn("BINANCE_TESTNET_ORDER_TEST_ONLY", audit["env_flags"])

    def test_exit_one_on_ok_false(self) -> None:
        code, audit = self._run_with_fake_executor(
            {
                "ok": False,
                "testnet": True,
                "live_trading": False,
                "dry_run": False,
                "order_test_only": True,
                "base_url": "https://testnet.binance.vision",
                "max_notional": 25.0,
                "allowed_symbols": ["BTCUSDT", "ETHUSDT"],
                "considered_count": 0,
                "placed_count": 0,
                "test_ok_count": 0,
                "rejected_count": 0,
                "skipped_count": 0,
                "reason": "ENABLE_BINANCE_TESTNET_EXECUTION is not '1'.",
                "warnings": None,
                "api_key_masked": None,
                "testnet_artifacts_dir": "/tmp/crypto_testnet",
            }
        )
        self.assertEqual(code, 1)
        self.assertIn("ENABLE_BINANCE_TESTNET_EXECUTION", audit["reason"])

    def test_audit_does_not_leak_secrets(self) -> None:
        code, audit = self._run_with_fake_executor(
            {
                "ok": True,
                "testnet": True,
                "live_trading": False,
                "dry_run": False,
                "order_test_only": True,
                "base_url": "https://testnet.binance.vision",
                "max_notional": 25.0,
                "allowed_symbols": ["BTCUSDT"],
                "considered_count": 0,
                "placed_count": 0,
                "test_ok_count": 0,
                "rejected_count": 0,
                "skipped_count": 0,
                "warnings": [],
                "api_key_masked": "****abcd",
                "testnet_artifacts_dir": "/tmp/crypto_testnet",
            }
        )
        self.assertEqual(code, 0)
        serialized = json.dumps(audit)
        self.assertNotIn("api_secret", serialized.lower())
        # Only the masked key should be exposed.
        self.assertEqual(audit["api_key_masked"], "****abcd")


class CLIDoesNotCallLiveBinanceTests(unittest.TestCase):
    def test_cli_passes_flags_through_to_executor_without_touching_network(self) -> None:
        captured_kwargs: dict[str, Any] = {}

        def _fake_executor(**kwargs: Any) -> dict[str, Any]:
            captured_kwargs.update(kwargs)
            return {
                "ok": True,
                "testnet": True,
                "live_trading": False,
                "dry_run": kwargs.get("dry_run"),
                "order_test_only": True,
                "base_url": "https://testnet.binance.vision",
                "max_notional": 25.0,
                "allowed_symbols": ["BTCUSDT"],
                "considered_count": 0,
                "placed_count": 0,
                "test_ok_count": 0,
                "rejected_count": 0,
                "skipped_count": 0,
                "warnings": [],
                "api_key_masked": None,
                "testnet_artifacts_dir": "/tmp/crypto_testnet",
            }

        buf = io.StringIO()
        with mock.patch.object(cli, "run_binance_testnet_execution", side_effect=_fake_executor), redirect_stdout(
            buf
        ):
            code = cli.main(
                [
                    "--paper-artifacts-dir",
                    "/tmp/x",
                    "--testnet-artifacts-dir",
                    "/tmp/y",
                    "--rebuild-semantic",
                    "--dry-run",
                ]
            )
        self.assertEqual(code, 0)
        self.assertEqual(captured_kwargs.get("paper_artifacts_dir"), "/tmp/x")
        self.assertEqual(captured_kwargs.get("testnet_artifacts_dir"), "/tmp/y")
        self.assertTrue(captured_kwargs.get("rebuild_semantic"))
        self.assertTrue(captured_kwargs.get("dry_run"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
