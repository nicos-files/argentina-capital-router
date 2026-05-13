import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from src.tools import notify_telegram as cli


def _write_plan(tmp: Path) -> Path:
    payload = {
        "as_of": "2026-05-12",
        "manual_review_only": True,
        "live_trading_enabled": False,
        "monthly_long_term_contribution_usd": 200.0,
        "routing_decision": {
            "decision": "INVEST_DIRECT_LONG_TERM",
            "rationale": "No tactical opportunity.",
        },
        "long_term_allocations": [
            {"symbol": "SPY", "asset_class": "cedear", "allocation_usd": 133.6},
            {"symbol": "AAPL", "asset_class": "cedear", "allocation_usd": 22.13},
        ],
        "warnings": [],
        "allocation_warnings": [],
        "skipped_allocations": [],
        "portfolio_total_value_usd": 170.83,
    }
    path = tmp / "daily_capital_plan.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_comparison(tmp: Path) -> Path:
    payload = {
        "follow_rate_pct": 50.0,
        "matched_symbols": 0,
        "partial_symbols": 1,
        "missed_symbols": 1,
        "extra_symbols": 0,
        "total_recommended_usd": 200.0,
        "total_executed_usd_estimate": 100.0,
        "total_fees_estimate": 1.0,
    }
    path = tmp / "manual_execution_comparison.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class NotifyTelegramCLITests(unittest.TestCase):
    def _run(self, args: list[str]) -> tuple[int, str, str]:
        out_buf = io.StringIO()
        err_buf = io.StringIO()
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            rc = cli.main(args)
        return rc, out_buf.getvalue(), err_buf.getvalue()

    def test_dry_run_without_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            plan = _write_plan(tmp)
            rc, out, _ = self._run(["--plan", str(plan), "--dry-run"])
            self.assertEqual(rc, 0, msg=out)
            self.assertIn("Manual review only", out)
            self.assertIn("dry_run: True", out)
            self.assertIn("sent: False", out)
            self.assertIn("Argentina Capital Router - 2026-05-12", out)

    def test_dry_run_with_execution_comparison_includes_follow_rate(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            plan = _write_plan(tmp)
            comparison = _write_comparison(tmp)
            rc, out, _ = self._run(
                [
                    "--plan",
                    str(plan),
                    "--execution-comparison",
                    str(comparison),
                    "--dry-run",
                ]
            )
            self.assertEqual(rc, 0, msg=out)
            self.assertIn("Follow rate: 50.0%", out)
            self.assertIn(
                "Matched: 0 | Partial: 1 | Missed: 1 | Extra: 0", out
            )

    def test_json_output_is_parseable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            plan = _write_plan(tmp)
            rc, out, _ = self._run(
                ["--plan", str(plan), "--dry-run", "--json"]
            )
            self.assertEqual(rc, 0, msg=out)
            payload = json.loads(out)
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["dry_run"])
            self.assertFalse(payload["sent"])
            self.assertEqual(payload["plan_path"], str(plan))
            self.assertIn("message_length", payload)

    def test_missing_plan_returns_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            rc, _, err = self._run(
                ["--plan", str(tmp / "nope.json"), "--dry-run"]
            )
            self.assertEqual(rc, 1)
            self.assertIn("not found", err)

    def test_missing_required_plan_arg_returns_usage(self) -> None:
        rc, _, err = self._run(["--dry-run"])
        self.assertEqual(rc, 2)
        self.assertTrue(err)

    def test_real_send_with_monkeypatched_notifier(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            plan = _write_plan(tmp)
            with mock.patch.object(
                cli,
                "send_telegram_message",
                return_value={
                    "ok": True,
                    "dry_run": False,
                    "sent": True,
                    "message_length": 100,
                },
            ) as send_mock:
                rc, out, _ = self._run(
                    [
                        "--plan",
                        str(plan),
                        "--bot-token",
                        "abc:fake",
                        "--chat-id",
                        "111",
                    ]
                )
            self.assertEqual(rc, 0, msg=out)
            send_mock.assert_called_once()
            # Token must not leak in stdout.
            self.assertNotIn("abc:fake", out)

    def test_real_send_failure_returns_failure_without_token_leak(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            plan = _write_plan(tmp)
            with mock.patch.object(
                cli,
                "send_telegram_message",
                side_effect=RuntimeError("Telegram API returned ok=false"),
            ):
                rc, _, err = self._run(
                    [
                        "--plan",
                        str(plan),
                        "--bot-token",
                        "abc:fake",
                        "--chat-id",
                        "111",
                    ]
                )
            self.assertEqual(rc, 1)
            self.assertIn("ok=false", err)
            self.assertNotIn("abc:fake", err)

    def test_no_forbidden_artifacts_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            plan = _write_plan(tmp)
            rc, _, _ = self._run(["--plan", str(plan), "--dry-run"])
            self.assertEqual(rc, 0)
            for forbidden in ("execution.plan", "final_decision.json"):
                for found in tmp.rglob(forbidden):
                    self.fail(f"unexpected forbidden artifact: {found}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
