import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from src.tools import compare_manual_execution as cli


REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_plan(tmp: Path) -> Path:
    payload = {
        "manual_review_only": True,
        "live_trading_enabled": False,
        "as_of": "2026-05-12",
        "long_term_allocations": [
            {
                "symbol": "SPY",
                "asset_class": "cedear",
                "bucket": "core_global_equity",
                "allocation_usd": 100.0,
                "rationale": "underweight",
            },
            {
                "symbol": "AAPL",
                "asset_class": "cedear",
                "bucket": "cedears_single_names",
                "allocation_usd": 50.0,
            },
        ],
    }
    path = tmp / "daily_capital_plan.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_executions(tmp: Path, currency: str = "USD") -> Path:
    if currency == "USD":
        prices = {"SPY": 100.0, "AAPL": 20.0}
    else:
        # ARS amounts that convert at 1200 ARS/USD back to the same USD totals.
        prices = {"SPY": 100.0 * 1200.0, "AAPL": 20.0 * 1200.0}
    payload = {
        "schema_version": "1.0",
        "execution_log_id": "manual-test",
        "as_of": "2026-05-12",
        "manual_review_only": True,
        "live_trading_enabled": False,
        "source": "manual",
        "broker": "TEST",
        "base_currency": "USD",
        "notes": "",
        "executions": [
            {
                "execution_id": "e-001",
                "plan_id": "2026-05-12",
                "symbol": "SPY",
                "asset_class": "cedear",
                "side": "BUY",
                "quantity": 1.0,
                "price": prices["SPY"],
                "price_currency": currency,
                "fees": 0.0,
                "fees_currency": currency,
                "executed_at": "2026-05-12",
                "broker": "TEST",
            },
            {
                "execution_id": "e-002",
                "plan_id": "2026-05-12",
                "symbol": "AAPL",
                "asset_class": "cedear",
                "side": "BUY",
                "quantity": 1.0,
                "price": prices["AAPL"],
                "price_currency": currency,
                "fees": 0.0,
                "fees_currency": currency,
                "executed_at": "2026-05-12",
                "broker": "TEST",
            },
        ],
        "quality": {"warnings": [], "completeness": "complete"},
    }
    path = tmp / "manual_executions.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class CompareManualExecutionTests(unittest.TestCase):
    def _run(self, args: list[str]) -> tuple[int, str, str]:
        out_buf = io.StringIO()
        err_buf = io.StringIO()
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            rc = cli.main(args)
        return rc, out_buf.getvalue(), err_buf.getvalue()

    def test_compares_and_writes_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            plan = _write_plan(tmp)
            executions = _write_executions(tmp)
            artifacts_dir = tmp / "artifacts"
            rc, out, _ = self._run(
                [
                    "--plan",
                    str(plan),
                    "--executions",
                    str(executions),
                    "--artifacts-dir",
                    str(artifacts_dir),
                ]
            )
            self.assertEqual(rc, 0, msg=out)
            self.assertIn("follow_rate_pct", out)
            json_path = (
                artifacts_dir / "manual_execution" / "manual_execution_comparison.json"
            )
            report_path = (
                artifacts_dir / "manual_execution" / "manual_execution_report.md"
            )
            self.assertTrue(json_path.exists())
            self.assertTrue(report_path.exists())
            self.assertFalse((artifacts_dir / "execution.plan").exists())
            self.assertFalse((artifacts_dir / "final_decision.json").exists())

    def test_json_output_is_parseable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            plan = _write_plan(tmp)
            executions = _write_executions(tmp)
            artifacts_dir = tmp / "artifacts"
            rc, out, _ = self._run(
                [
                    "--plan",
                    str(plan),
                    "--executions",
                    str(executions),
                    "--artifacts-dir",
                    str(artifacts_dir),
                    "--json",
                ]
            )
            self.assertEqual(rc, 0, msg=out)
            payload = json.loads(out)
            self.assertIs(payload["manual_review_only"], True)
            self.assertIs(payload["live_trading_enabled"], False)
            self.assertIn("items", payload)
            self.assertIn("artifacts", payload)
            self.assertEqual(payload["matched_symbols"], 1)
            self.assertEqual(payload["partial_symbols"], 1)

    def test_missing_args_returns_usage_error(self) -> None:
        rc, _, err = self._run([])
        self.assertEqual(rc, 2)
        self.assertTrue(err)  # argparse prints an error message

    def test_invalid_execution_log_returns_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            plan = _write_plan(tmp)
            bad = tmp / "bad.json"
            bad.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "execution_log_id": "bad",
                        "as_of": "2026-05-12",
                        "manual_review_only": True,
                        "live_trading_enabled": True,  # forbidden
                        "source": "manual",
                        "broker": "T",
                        "base_currency": "USD",
                        "notes": "",
                        "executions": [],
                    }
                ),
                encoding="utf-8",
            )
            rc, _, err = self._run(
                ["--plan", str(plan), "--executions", str(bad)]
            )
            self.assertEqual(rc, 1)
            self.assertIn("live_trading_enabled", err)

    def test_usdars_rate_converts_ars_to_usd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            plan = _write_plan(tmp)
            executions = _write_executions(tmp, currency="ARS")
            artifacts_dir = tmp / "artifacts"
            rc, out, _ = self._run(
                [
                    "--plan",
                    str(plan),
                    "--executions",
                    str(executions),
                    "--artifacts-dir",
                    str(artifacts_dir),
                    "--usdars-rate",
                    "1200",
                    "--json",
                ]
            )
            self.assertEqual(rc, 0, msg=out)
            payload = json.loads(out)
            self.assertAlmostEqual(
                payload["total_executed_usd_estimate"], 120.0, places=2
            )
            # No "treated as USD-equivalent" warning when FX rate is provided.
            self.assertFalse(
                any(
                    "treated as USD-equivalent" in w
                    for w in payload.get("warnings", [])
                )
            )

    def test_no_forbidden_artifacts_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            plan = _write_plan(tmp)
            executions = _write_executions(tmp)
            artifacts_dir = tmp / "artifacts"
            rc, _, _ = self._run(
                [
                    "--plan",
                    str(plan),
                    "--executions",
                    str(executions),
                    "--artifacts-dir",
                    str(artifacts_dir),
                ]
            )
            self.assertEqual(rc, 0)
            for forbidden in ("execution.plan", "final_decision.json"):
                for path in tmp.rglob(forbidden):
                    self.fail(f"unexpected forbidden artifact: {path}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
