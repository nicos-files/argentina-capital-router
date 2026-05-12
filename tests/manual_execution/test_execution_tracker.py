import copy
import json
import tempfile
import unittest
from pathlib import Path

from src.manual_execution.execution_tracker import (
    EXTRA,
    MATCHED,
    MISSED,
    PARTIAL,
    ManualExecution,
    build_manual_execution_report,
    compare_plan_to_manual_executions,
    estimate_execution_usd,
    load_manual_execution_log,
    load_plan_allocations,
    write_execution_comparison_artifacts,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_LOG = (
    REPO_ROOT / "config" / "manual_execution" / "manual_executions.example.json"
)
TEMPLATE_LOG = (
    REPO_ROOT / "config" / "manual_execution" / "manual_executions.template.json"
)


def _base_log_payload() -> dict:
    return json.loads(EXAMPLE_LOG.read_text(encoding="utf-8"))


def _write_log(tmp: Path, payload: dict, name: str = "log.json") -> Path:
    target = tmp / name
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


def _write_plan(tmp: Path, allocations: list[dict], name: str = "plan.json") -> Path:
    target = tmp / name
    payload = {
        "manual_review_only": True,
        "live_trading_enabled": False,
        "long_term_allocations": allocations,
        "as_of": "2026-05-12",
    }
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


class LoadManualExecutionLogTests(unittest.TestCase):
    def test_loads_example_log(self) -> None:
        log = load_manual_execution_log(EXAMPLE_LOG)
        self.assertEqual(log.execution_log_id, "manual-executions-example-2026-05-12")
        self.assertEqual(len(log.executions), 3)
        self.assertTrue(log.manual_review_only)
        self.assertFalse(log.live_trading_enabled)

    def test_loads_template_log(self) -> None:
        log = load_manual_execution_log(TEMPLATE_LOG)
        self.assertEqual(log.execution_log_id, "manual-executions-TODO")
        self.assertEqual(len(log.executions), 1)

    def test_rejects_live_trading_enabled_true(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            payload = _base_log_payload()
            payload["live_trading_enabled"] = True
            path = _write_log(tmp, payload)
            with self.assertRaisesRegex(ValueError, "live_trading_enabled"):
                load_manual_execution_log(path)

    def test_rejects_manual_review_only_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            payload = _base_log_payload()
            payload["manual_review_only"] = False
            path = _write_log(tmp, payload)
            with self.assertRaisesRegex(ValueError, "manual_review_only"):
                load_manual_execution_log(path)

    def test_rejects_invalid_side(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            payload = _base_log_payload()
            payload["executions"][0]["side"] = "HOLD"
            path = _write_log(tmp, payload)
            with self.assertRaisesRegex(ValueError, "side must be one of"):
                load_manual_execution_log(path)

    def test_rejects_non_positive_quantity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            payload = _base_log_payload()
            payload["executions"][0]["quantity"] = 0
            path = _write_log(tmp, payload)
            with self.assertRaisesRegex(ValueError, "quantity must be > 0"):
                load_manual_execution_log(path)

    def test_rejects_non_positive_price(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            payload = _base_log_payload()
            payload["executions"][0]["price"] = -1
            path = _write_log(tmp, payload)
            with self.assertRaisesRegex(ValueError, "price must be > 0"):
                load_manual_execution_log(path)

    def test_rejects_negative_fees(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            payload = _base_log_payload()
            payload["executions"][0]["fees"] = -10
            path = _write_log(tmp, payload)
            with self.assertRaisesRegex(ValueError, "fees must be >= 0"):
                load_manual_execution_log(path)


class LoadPlanAllocationsTests(unittest.TestCase):
    def test_parses_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            path = _write_plan(
                tmp,
                [
                    {
                        "symbol": "SPY",
                        "asset_class": "cedear",
                        "bucket": "core_global_equity",
                        "allocation_usd": 133.6,
                        "rationale": "underweight",
                    },
                    {
                        "symbol": "AAPL",
                        "asset_class": "cedear",
                        "bucket": "cedears_single_names",
                        "allocation_usd": 22.13,
                    },
                ],
            )
            allocations = load_plan_allocations(path)
            self.assertEqual([a.symbol for a in allocations], ["SPY", "AAPL"])
            self.assertEqual(allocations[0].recommended_usd, 133.6)
            self.assertEqual(allocations[0].rationale, "underweight")

    def test_rejects_missing_long_term_allocations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            path = tmp / "plan.json"
            path.write_text(json.dumps({"manual_review_only": True}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "long_term_allocations"):
                load_plan_allocations(path)

    def test_rejects_live_trading_enabled_true(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            path = tmp / "plan.json"
            path.write_text(
                json.dumps(
                    {
                        "manual_review_only": True,
                        "live_trading_enabled": True,
                        "long_term_allocations": [],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "live_trading_enabled"):
                load_plan_allocations(path)


class EstimateExecutionUsdTests(unittest.TestCase):
    def _execution(self, **overrides) -> ManualExecution:
        kwargs = dict(
            execution_id="m-001",
            plan_id="2026-05-12",
            symbol="SPY",
            asset_class="cedear",
            side="BUY",
            quantity=2.0,
            price=10000.0,
            price_currency="ARS",
            fees=200.0,
            fees_currency="ARS",
            executed_at="2026-05-12",
            broker="IOL",
            notes="",
        )
        kwargs.update(overrides)
        return ManualExecution(**kwargs)

    def test_usd_amounts_pass_through(self) -> None:
        execution = self._execution(
            price=100.0,
            price_currency="USD",
            fees=1.0,
            fees_currency="USD",
        )
        executed_usd, fees_usd, warnings = estimate_execution_usd(execution)
        self.assertAlmostEqual(executed_usd, 200.0)
        self.assertAlmostEqual(fees_usd, 1.0)
        self.assertEqual(warnings, [])

    def test_ars_converts_with_rate(self) -> None:
        execution = self._execution()
        executed_usd, fees_usd, warnings = estimate_execution_usd(
            execution, default_usdars_rate=1000.0
        )
        # 2 * 10000 = 20000 ARS / 1000 = 20 USD; fees 200 / 1000 = 0.20
        self.assertAlmostEqual(executed_usd, 20.0)
        self.assertAlmostEqual(fees_usd, 0.20)
        self.assertEqual(warnings, [])

    def test_ars_without_fx_emits_warning_and_falls_back(self) -> None:
        execution = self._execution()
        executed_usd, fees_usd, warnings = estimate_execution_usd(execution)
        self.assertAlmostEqual(executed_usd, 20000.0)
        self.assertAlmostEqual(fees_usd, 200.0)
        self.assertTrue(
            any("treated as USD-equivalent" in w for w in warnings),
            msg=warnings,
        )

    def test_fx_rates_mapping_is_preferred_over_default(self) -> None:
        execution = self._execution()
        executed_usd, _, warnings = estimate_execution_usd(
            execution,
            fx_rates={"USDARS_MEP": 2000.0},
            default_usdars_rate=1.0,  # should be ignored
        )
        self.assertAlmostEqual(executed_usd, 10.0)
        self.assertEqual(warnings, [])


class ComparePlanToManualExecutionsTests(unittest.TestCase):
    def _build_plan(self, tmp: Path) -> Path:
        return _write_plan(
            tmp,
            [
                {
                    "symbol": "SPY",
                    "asset_class": "cedear",
                    "bucket": "core_global_equity",
                    "allocation_usd": 100.0,
                },
                {
                    "symbol": "AAPL",
                    "asset_class": "cedear",
                    "bucket": "cedears_single_names",
                    "allocation_usd": 50.0,
                },
                {
                    "symbol": "KO",
                    "asset_class": "cedear",
                    "bucket": "cedears_single_names",
                    "allocation_usd": 50.0,
                },
            ],
        )

    def _build_log(self, tmp: Path) -> Path:
        # SPY: 100 USD recommended, executed ~100 USD => MATCHED
        # AAPL: 50 USD recommended, executed 20 USD => PARTIAL
        # KO: 50 USD recommended, executed 0 => MISSED
        # GGAL: not in plan, executed 30 USD => EXTRA
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
                    "price": 100.0,
                    "price_currency": "USD",
                    "fees": 1.0,
                    "fees_currency": "USD",
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
                    "price": 20.0,
                    "price_currency": "USD",
                    "fees": 0.5,
                    "fees_currency": "USD",
                    "executed_at": "2026-05-12",
                    "broker": "TEST",
                },
                {
                    "execution_id": "e-003",
                    "plan_id": "2026-05-12",
                    "symbol": "GGAL",
                    "asset_class": "argentina_equity",
                    "side": "BUY",
                    "quantity": 1.0,
                    "price": 30.0,
                    "price_currency": "USD",
                    "fees": 0.0,
                    "fees_currency": "USD",
                    "executed_at": "2026-05-12",
                    "broker": "TEST",
                },
            ],
            "quality": {"warnings": [], "completeness": "complete"},
        }
        return _write_log(tmp, payload)

    def test_matched_partial_missed_and_extra(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            plan = self._build_plan(tmp)
            log = self._build_log(tmp)
            summary = compare_plan_to_manual_executions(plan, log)

            by_symbol = {item.symbol: item for item in summary.items}
            self.assertEqual(by_symbol["SPY"].status, MATCHED)
            self.assertEqual(by_symbol["AAPL"].status, PARTIAL)
            self.assertEqual(by_symbol["KO"].status, MISSED)
            self.assertEqual(by_symbol["GGAL"].status, EXTRA)

            self.assertEqual(summary.matched_symbols, 1)
            self.assertEqual(summary.partial_symbols, 1)
            self.assertEqual(summary.missed_symbols, 1)
            self.assertEqual(summary.extra_symbols, 1)

            self.assertAlmostEqual(summary.total_recommended_usd, 200.0)
            self.assertAlmostEqual(summary.total_executed_usd_estimate, 150.0)
            self.assertAlmostEqual(summary.total_fees_estimate, 1.5)

            # follow rate: matched + partial = 2 out of 3 recommended symbols.
            self.assertAlmostEqual(summary.follow_rate_pct, (2 / 3) * 100.0)

    def test_empty_plan_yields_zero_follow_rate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            plan = _write_plan(tmp, [])
            log = self._build_log(tmp)
            summary = compare_plan_to_manual_executions(plan, log)
            self.assertEqual(summary.follow_rate_pct, 0.0)
            # All executions become EXTRA.
            self.assertEqual(summary.extra_symbols, 3)

    def test_writes_artifacts_and_no_forbidden_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            plan = self._build_plan(tmp)
            log = self._build_log(tmp)
            summary = compare_plan_to_manual_executions(plan, log)
            artifacts = write_execution_comparison_artifacts(summary, tmp / "out")

            json_path = Path(artifacts["manual_execution_comparison"])
            report_path = Path(artifacts["manual_execution_report"])
            self.assertTrue(json_path.exists())
            self.assertTrue(report_path.exists())

            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertIs(payload["manual_review_only"], True)
            self.assertIs(payload["live_trading_enabled"], False)
            self.assertEqual(len(payload["items"]), 4)

            report = report_path.read_text(encoding="utf-8")
            self.assertIn("MANUAL REVIEW ONLY", report)
            self.assertIn("Follow rate", report)
            self.assertIn("MATCHED", report)
            self.assertIn("PARTIAL", report)
            self.assertIn("MISSED", report)
            self.assertIn("EXTRA", report)

            self.assertFalse((tmp / "out" / "execution.plan").exists())
            self.assertFalse((tmp / "out" / "final_decision.json").exists())
            self.assertFalse(
                (tmp / "out" / "manual_execution" / "execution.plan").exists()
            )
            self.assertFalse(
                (tmp / "out" / "manual_execution" / "final_decision.json").exists()
            )


class BuildManualExecutionReportTests(unittest.TestCase):
    def test_report_contains_no_crypto_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            plan = _write_plan(
                tmp,
                [
                    {
                        "symbol": "SPY",
                        "asset_class": "cedear",
                        "bucket": "core_global_equity",
                        "allocation_usd": 100.0,
                    }
                ],
            )
            payload = _base_log_payload()
            # Keep only the SPY entry so totals are predictable.
            payload["executions"] = [
                copy.deepcopy(payload["executions"][0])
            ]
            log_path = _write_log(tmp, payload)
            summary = compare_plan_to_manual_executions(
                plan, log_path, default_usdars_rate=1200.0
            )
            report = build_manual_execution_report(summary)
            self.assertNotIn("crypto", report.lower())
            self.assertIn("MANUAL REVIEW ONLY", report)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
