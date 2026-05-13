import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from src.tools import run_manual_daily_workflow as cli


REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_MARKET = (
    REPO_ROOT / "config" / "data_inputs" / "manual_market_snapshot.example.json"
)
EXAMPLE_PORTFOLIO = (
    REPO_ROOT / "config" / "portfolio" / "manual_portfolio_snapshot.example.json"
)
EXAMPLE_EXECUTIONS = (
    REPO_ROOT
    / "config"
    / "manual_execution"
    / "manual_executions.example.json"
)
TEMPLATE_MARKET = (
    REPO_ROOT
    / "config"
    / "data_inputs"
    / "manual_market_snapshot.template.json"
)
TEMPLATE_PORTFOLIO = (
    REPO_ROOT
    / "config"
    / "portfolio"
    / "manual_portfolio_snapshot.template.json"
)


def _scrub_notes(obj):
    """Recursively clear ``notes`` strings to avoid tripping TODO checks."""
    if isinstance(obj, dict):
        for key, value in list(obj.items()):
            if key == "notes" and isinstance(value, str):
                obj[key] = ""
            else:
                _scrub_notes(value)
    elif isinstance(obj, list):
        for item in obj:
            _scrub_notes(item)
    return obj


def _write_complete_snapshots(tmp: Path) -> tuple[Path, Path]:
    """Return (market, portfolio) snapshots tweaked to pass --strict-inputs."""
    market_raw = json.loads(EXAMPLE_MARKET.read_text(encoding="utf-8"))
    market_raw["quality"] = {"warnings": [], "completeness": "complete"}
    _scrub_notes(market_raw)
    market_path = tmp / "market_complete.json"
    market_path.write_text(json.dumps(market_raw), encoding="utf-8")

    portfolio_raw = json.loads(EXAMPLE_PORTFOLIO.read_text(encoding="utf-8"))
    # Example market only prices SPY + GGAL; drop AAPL so strict mode passes.
    portfolio_raw["positions"] = [
        p for p in portfolio_raw["positions"] if p["symbol"] in {"SPY", "GGAL"}
    ]
    portfolio_raw["quality"] = {"warnings": [], "completeness": "complete"}
    _scrub_notes(portfolio_raw)
    portfolio_path = tmp / "portfolio_complete.json"
    portfolio_path.write_text(json.dumps(portfolio_raw), encoding="utf-8")

    return market_path, portfolio_path


class RunManualDailyWorkflowTests(unittest.TestCase):
    def _run(self, args: list[str]) -> tuple[int, str, str]:
        out_buf = io.StringIO()
        err_buf = io.StringIO()
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            rc = cli.main(args)
        return rc, out_buf.getvalue(), err_buf.getvalue()

    def test_runs_with_market_and_portfolio_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            rc, out, _ = self._run(
                [
                    "--date",
                    "2026-05-12",
                    "--market-snapshot",
                    str(EXAMPLE_MARKET),
                    "--portfolio-snapshot",
                    str(EXAMPLE_PORTFOLIO),
                    "--artifacts-dir",
                    str(tmp),
                ]
            )
            self.assertEqual(rc, 0, msg=out)
            self.assertIn("Manual review only", out)
            self.assertIn("daily_plan", out)

            self.assertTrue(
                (tmp / "capital_routing" / "daily_capital_plan.json").exists()
            )
            self.assertTrue(
                (
                    tmp / "long_term" / "monthly_contribution_plan.json"
                ).exists()
            )
            self.assertTrue((tmp / "reports" / "daily_report.md").exists())

            self.assertIn(
                "execution_comparison: skipped (no --executions provided)",
                out,
            )
            self.assertFalse(
                (tmp / "manual_execution").exists(),
                msg="manual_execution dir should not exist without --executions",
            )

    def test_runs_with_executions_and_writes_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            rc, out, _ = self._run(
                [
                    "--date",
                    "2026-05-12",
                    "--market-snapshot",
                    str(EXAMPLE_MARKET),
                    "--portfolio-snapshot",
                    str(EXAMPLE_PORTFOLIO),
                    "--executions",
                    str(EXAMPLE_EXECUTIONS),
                    "--usdars-rate",
                    "1200",
                    "--artifacts-dir",
                    str(tmp),
                ]
            )
            self.assertEqual(rc, 0, msg=out)
            comparison_dir = tmp / "manual_execution"
            self.assertTrue(comparison_dir.exists())
            self.assertTrue(
                (comparison_dir / "manual_execution_comparison.json").exists()
            )
            self.assertTrue(
                (comparison_dir / "manual_execution_report.md").exists()
            )
            self.assertIn("follow_rate_pct", out)

    def test_json_output_is_parseable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            rc, out, _ = self._run(
                [
                    "--date",
                    "2026-05-12",
                    "--market-snapshot",
                    str(EXAMPLE_MARKET),
                    "--portfolio-snapshot",
                    str(EXAMPLE_PORTFOLIO),
                    "--executions",
                    str(EXAMPLE_EXECUTIONS),
                    "--usdars-rate",
                    "1200",
                    "--artifacts-dir",
                    str(tmp),
                    "--json",
                ]
            )
            self.assertEqual(rc, 0, msg=out)
            payload = json.loads(out)
            self.assertIs(payload["manual_review_only"], True)
            self.assertIs(payload["live_trading_enabled"], False)
            self.assertEqual(payload["date"], "2026-05-12")
            self.assertEqual(payload["status"], "ok")
            self.assertIn("daily_plan_path", payload)
            self.assertIn("daily_report_path", payload)
            self.assertIn("execution_comparison_path", payload)
            self.assertIn("follow_rate_pct", payload)
            self.assertEqual(
                payload["market_snapshot"], str(EXAMPLE_MARKET)
            )
            self.assertEqual(
                payload["portfolio_snapshot"], str(EXAMPLE_PORTFOLIO)
            )

    def test_missing_required_arg_exits_usage_error(self) -> None:
        rc, _, err = self._run(
            ["--portfolio-snapshot", str(EXAMPLE_PORTFOLIO)]
        )
        self.assertEqual(rc, 2)
        self.assertTrue(err)

    def test_strict_inputs_fails_on_placeholder_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            rc, out, _ = self._run(
                [
                    "--date",
                    "2026-05-12",
                    "--market-snapshot",
                    str(TEMPLATE_MARKET),
                    "--portfolio-snapshot",
                    str(TEMPLATE_PORTFOLIO),
                    "--artifacts-dir",
                    str(tmp),
                    "--strict-inputs",
                ]
            )
            self.assertEqual(rc, 1, msg=out)
            self.assertIn("strict_failed", out)
            # No daily plan should be written when strict validation fails.
            self.assertFalse(
                (tmp / "capital_routing" / "daily_capital_plan.json").exists()
            )

    def test_strict_inputs_fails_on_template_todos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            rc, out, _ = self._run(
                [
                    "--date",
                    "2026-05-12",
                    "--market-snapshot",
                    str(TEMPLATE_MARKET),
                    "--portfolio-snapshot",
                    str(TEMPLATE_PORTFOLIO),
                    "--artifacts-dir",
                    str(tmp),
                    "--strict-inputs",
                    "--json",
                ]
            )
            self.assertEqual(rc, 1, msg=out)
            payload = json.loads(out)
            self.assertEqual(payload["input_validation_status"], "strict_failed")
            self.assertFalse(payload["input_quality_ok"])
            self.assertGreater(payload["input_quality_errors_count"], 0)
            self.assertFalse(
                (tmp / "capital_routing" / "daily_capital_plan.json").exists()
            )

    def test_strict_inputs_fails_on_date_mismatch_before_writing_plan(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            market, portfolio = _write_complete_snapshots(tmp)
            artifacts = tmp / "artifacts"
            rc, out, _ = self._run(
                [
                    # Snapshots are dated 2026-05-12; ask for 2026-05-13.
                    "--date",
                    "2026-05-13",
                    "--market-snapshot",
                    str(market),
                    "--portfolio-snapshot",
                    str(portfolio),
                    "--artifacts-dir",
                    str(artifacts),
                    "--strict-inputs",
                ]
            )
            self.assertEqual(rc, 1, msg=out)
            self.assertIn("strict_failed", out)
            # No daily plan should be written when strict validation fails on
            # the date mismatch.
            self.assertFalse(
                (
                    artifacts / "capital_routing" / "daily_capital_plan.json"
                ).exists()
            )

    def test_non_strict_template_still_runs_with_quality_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            rc, out, _ = self._run(
                [
                    "--date",
                    "2026-05-12",
                    "--market-snapshot",
                    str(TEMPLATE_MARKET),
                    "--portfolio-snapshot",
                    str(TEMPLATE_PORTFOLIO),
                    "--artifacts-dir",
                    str(tmp),
                    "--json",
                ]
            )
            self.assertEqual(rc, 0, msg=out)
            payload = json.loads(out)
            self.assertEqual(payload["input_validation_status"], "valid")
            # Quality reports the template's placeholder values as warnings
            # but does not block the workflow.
            self.assertIn("input_quality_ok", payload)
            self.assertTrue(payload["input_quality_ok"])
            self.assertGreater(payload["input_quality_warnings_count"], 0)
            self.assertTrue(
                (tmp / "capital_routing" / "daily_capital_plan.json").exists()
            )

    def test_json_includes_input_quality_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            rc, out, _ = self._run(
                [
                    "--date",
                    "2026-05-12",
                    "--market-snapshot",
                    str(EXAMPLE_MARKET),
                    "--portfolio-snapshot",
                    str(EXAMPLE_PORTFOLIO),
                    "--artifacts-dir",
                    str(tmp),
                    "--json",
                ]
            )
            self.assertEqual(rc, 0, msg=out)
            payload = json.loads(out)
            self.assertIn("input_quality_ok", payload)
            self.assertIn("input_quality_errors_count", payload)
            self.assertIn("input_quality_warnings_count", payload)

    def test_strict_inputs_succeeds_with_complete_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            market, portfolio = _write_complete_snapshots(tmp)
            artifacts = tmp / "artifacts"
            rc, out, _ = self._run(
                [
                    "--date",
                    "2026-05-12",
                    "--market-snapshot",
                    str(market),
                    "--portfolio-snapshot",
                    str(portfolio),
                    "--artifacts-dir",
                    str(artifacts),
                    "--strict-inputs",
                ]
            )
            self.assertEqual(rc, 0, msg=out)

    def test_no_forbidden_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            rc, _, _ = self._run(
                [
                    "--date",
                    "2026-05-12",
                    "--market-snapshot",
                    str(EXAMPLE_MARKET),
                    "--portfolio-snapshot",
                    str(EXAMPLE_PORTFOLIO),
                    "--executions",
                    str(EXAMPLE_EXECUTIONS),
                    "--usdars-rate",
                    "1200",
                    "--artifacts-dir",
                    str(tmp),
                ]
            )
            self.assertEqual(rc, 0)
            for forbidden in ("execution.plan", "final_decision.json"):
                for found in tmp.rglob(forbidden):
                    self.fail(f"unexpected forbidden artifact: {found}")

    def test_no_crypto_or_broker_or_network_references_in_outputs(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            rc, out, _ = self._run(
                [
                    "--date",
                    "2026-05-12",
                    "--market-snapshot",
                    str(EXAMPLE_MARKET),
                    "--portfolio-snapshot",
                    str(EXAMPLE_PORTFOLIO),
                    "--artifacts-dir",
                    str(tmp),
                ]
            )
            self.assertEqual(rc, 0)
            report = (tmp / "reports" / "daily_report.md").read_text(
                encoding="utf-8"
            )
            for forbidden_word in ("crypto", "binance"):
                self.assertNotIn(forbidden_word, report.lower())
                self.assertNotIn(forbidden_word, out.lower())

    def test_invalid_market_snapshot_returns_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            bad = tmp / "bad.json"
            bad.write_text("not-json", encoding="utf-8")
            rc, _, _ = self._run(
                [
                    "--date",
                    "2026-05-12",
                    "--market-snapshot",
                    str(bad),
                    "--portfolio-snapshot",
                    str(EXAMPLE_PORTFOLIO),
                    "--artifacts-dir",
                    str(tmp / "out"),
                ]
            )
            self.assertEqual(rc, 1)
            self.assertFalse((tmp / "out").exists())

    def test_telegram_dry_run_without_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            rc, out, _ = self._run(
                [
                    "--date",
                    "2026-05-12",
                    "--market-snapshot",
                    str(EXAMPLE_MARKET),
                    "--portfolio-snapshot",
                    str(EXAMPLE_PORTFOLIO),
                    "--artifacts-dir",
                    str(tmp),
                    "--telegram-dry-run",
                    "--json",
                ]
            )
            self.assertEqual(rc, 0, msg=out)
            payload = json.loads(out)
            self.assertIn("telegram", payload)
            tg = payload["telegram"]
            self.assertTrue(tg["ok"])
            self.assertTrue(tg["dry_run"])
            self.assertFalse(tg["sent"])
            self.assertIn("message_preview", tg)
            self.assertIn(
                "Argentina Capital Router - 2026-05-12", tg["message_preview"]
            )

    def test_notify_telegram_with_monkeypatched_send_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            with mock.patch.object(
                cli,
                "send_telegram_message",
                return_value={
                    "ok": True,
                    "dry_run": False,
                    "sent": True,
                    "message_length": 123,
                },
            ) as send_mock, mock.patch.object(
                cli,
                "load_telegram_config",
                return_value=cli.TelegramConfig(
                    bot_token="abc:fake", chat_id="111"
                ),
            ):
                rc, out, _ = self._run(
                    [
                        "--date",
                        "2026-05-12",
                        "--market-snapshot",
                        str(EXAMPLE_MARKET),
                        "--portfolio-snapshot",
                        str(EXAMPLE_PORTFOLIO),
                        "--artifacts-dir",
                        str(tmp),
                        "--notify-telegram",
                        "--json",
                    ]
                )
            self.assertEqual(rc, 0, msg=out)
            send_mock.assert_called_once()
            payload = json.loads(out)
            self.assertTrue(payload["telegram"]["ok"])
            self.assertTrue(payload["telegram"]["sent"])
            self.assertFalse(payload["telegram"]["dry_run"])
            # Token must never leak in stdout (human or json paths).
            self.assertNotIn("abc:fake", out)

    def test_notify_telegram_failure_returns_nonzero_but_keeps_artifacts(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            with mock.patch.object(
                cli,
                "send_telegram_message",
                side_effect=RuntimeError("Telegram API returned ok=false"),
            ), mock.patch.object(
                cli,
                "load_telegram_config",
                return_value=cli.TelegramConfig(
                    bot_token="abc:fake", chat_id="111"
                ),
            ):
                rc, out, _ = self._run(
                    [
                        "--date",
                        "2026-05-12",
                        "--market-snapshot",
                        str(EXAMPLE_MARKET),
                        "--portfolio-snapshot",
                        str(EXAMPLE_PORTFOLIO),
                        "--artifacts-dir",
                        str(tmp),
                        "--notify-telegram",
                    ]
                )
            self.assertEqual(rc, 1, msg=out)
            # Daily artifacts must still exist after a Telegram failure.
            self.assertTrue(
                (tmp / "capital_routing" / "daily_capital_plan.json").exists()
            )
            self.assertTrue((tmp / "reports" / "daily_report.md").exists())
            self.assertIn("ok=false", out)
            self.assertNotIn("abc:fake", out)

    def test_default_artifacts_dir_uses_snapshots_outputs_date(self) -> None:
        # Verify the resolver without writing to the real repo path.
        from src.tools.run_manual_daily_workflow import _resolve_artifacts_dir

        resolved = _resolve_artifacts_dir(None, "2026-05-12")
        self.assertEqual(
            resolved.parts[-2:],
            ("outputs", "2026-05-12"),
            msg=f"unexpected resolved path: {resolved}",
        )
        self.assertEqual(
            resolved.parts[-3], "snapshots", msg=f"resolved={resolved}"
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
