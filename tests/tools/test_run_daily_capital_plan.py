import json
import sys
import tempfile
import unittest
from pathlib import Path

from src.tools import run_daily_capital_plan as cli


REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_SNAPSHOT = (
    REPO_ROOT / "config" / "data_inputs" / "manual_market_snapshot.example.json"
)
EXAMPLE_PORTFOLIO = (
    REPO_ROOT / "config" / "portfolio" / "manual_portfolio_snapshot.example.json"
)


class RunDailyCapitalPlanTests(unittest.TestCase):
    def _run(self, extra_args: list[str], tmp: Path) -> int:
        argv = [
            "--as-of",
            "2026-05-12",
            "--monthly-contribution-usd",
            "200",
            "--artifacts-dir",
            str(tmp),
            *extra_args,
        ]
        return cli.main(argv)

    def test_default_run_produces_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            rc = self._run([], tmp)
            self.assertEqual(rc, 0)

            plan_path = tmp / "capital_routing" / "daily_capital_plan.json"
            contrib_path = tmp / "long_term" / "monthly_contribution_plan.json"
            report_path = tmp / "reports" / "daily_report.md"
            self.assertTrue(plan_path.exists())
            self.assertTrue(contrib_path.exists())
            self.assertTrue(report_path.exists())

            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertIs(plan["manual_review_only"], True)
            self.assertIs(plan["live_trading_enabled"], False)
            self.assertEqual(plan["monthly_long_term_contribution_usd"], 200)
            self.assertEqual(
                plan["routing_decision"]["decision"], "INVEST_DIRECT_LONG_TERM"
            )
            self.assertGreater(len(plan["long_term_allocations"]), 0)

            # No execution.plan / final_decision.json artifacts must exist.
            self.assertFalse((tmp / "execution.plan").exists())
            self.assertFalse((tmp / "final_decision.json").exists())

            report = report_path.read_text(encoding="utf-8")
            self.assertIn("MANUAL REVIEW ONLY", report)
            self.assertNotIn("crypto", report.lower())

    def test_simulate_carry_routes_to_tactical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            rc = self._run(
                [
                    "--simulate-carry",
                    "--carry-rate-pct",
                    "8.0",
                    "--carry-fx-devaluation-pct",
                    "2.0",
                    "--carry-cost-pct",
                    "0.5",
                    "--carry-duration-days",
                    "7",
                    "--carry-fx-risk-score",
                    "30",
                    "--carry-liquidity-risk-score",
                    "30",
                ],
                tmp,
            )
            self.assertEqual(rc, 0)
            plan_path = tmp / "capital_routing" / "daily_capital_plan.json"
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertIs(plan["manual_review_only"], True)
            self.assertIs(plan["live_trading_enabled"], False)
            self.assertEqual(
                plan["routing_decision"]["decision"], "TACTICAL_THEN_LONG_TERM"
            )


class RunDailyCapitalPlanWithSnapshotTests(unittest.TestCase):
    def _run(self, extra_args: list[str], tmp: Path) -> int:
        argv = [
            "--as-of",
            "2026-05-12",
            "--monthly-contribution-usd",
            "200",
            "--artifacts-dir",
            str(tmp),
            *extra_args,
        ]
        return cli.main(argv)

    def test_with_snapshot_includes_snapshot_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            rc = self._run(["--market-snapshot", str(EXAMPLE_SNAPSHOT)], tmp)
            self.assertEqual(rc, 0)
            plan = json.loads(
                (tmp / "capital_routing" / "daily_capital_plan.json").read_text(encoding="utf-8")
            )
            self.assertIs(plan["manual_review_only"], True)
            self.assertIs(plan["live_trading_enabled"], False)
            self.assertEqual(
                plan["market_snapshot_id"], "manual-example-2026-05-12"
            )
            self.assertGreaterEqual(len(plan["prices_used"]), 2)
            self.assertGreaterEqual(len(plan["fx_rates_used"]), 1)
            self.assertGreaterEqual(len(plan["rate_inputs_used"]), 1)
            self.assertGreaterEqual(len(plan["data_warnings"]), 1)
            self.assertEqual(
                plan["metadata"]["market_snapshot"]["snapshot_id"],
                "manual-example-2026-05-12",
            )
            # No order artifacts
            self.assertFalse((tmp / "execution.plan").exists())
            self.assertFalse((tmp / "final_decision.json").exists())

            # Report contains expected sections
            report = (tmp / "reports" / "daily_report.md").read_text(encoding="utf-8")
            self.assertIn("MANUAL REVIEW ONLY", report)
            self.assertIn("## Market Snapshot", report)
            self.assertIn("## FX Rates Used", report)
            self.assertIn("## Rate Inputs Used", report)
            self.assertIn("## Data Warnings", report)

    def test_with_snapshot_and_carry_from_snapshot_routes_capital(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            rc = self._run(
                [
                    "--market-snapshot",
                    str(EXAMPLE_SNAPSHOT),
                    "--carry-from-snapshot",
                    "--carry-duration-days",
                    "7",
                    "--carry-fx-risk-score",
                    "30",
                    "--carry-liquidity-risk-score",
                    "30",
                ],
                tmp,
            )
            self.assertEqual(rc, 0)
            plan = json.loads(
                (tmp / "capital_routing" / "daily_capital_plan.json").read_text(encoding="utf-8")
            )
            # The CLI must have scored the carry opportunity from the snapshot and
            # routed capital. Whether tactical or long-term depends on policy thresholds
            # vs the example values - either outcome is valid, but the opportunity
            # provenance must be present in metadata.
            decision = plan["routing_decision"]["decision"]
            self.assertIn(
                decision,
                {"TACTICAL_THEN_LONG_TERM", "INVEST_DIRECT_LONG_TERM"},
            )
            self.assertTrue(plan["metadata"]["opportunity_from_snapshot"])
            self.assertEqual(plan["routing_decision"]["opportunity_id"], "snapshot_carry")
            self.assertIs(plan["manual_review_only"], True)
            self.assertIs(plan["live_trading_enabled"], False)

    def test_rejects_simulate_carry_and_carry_from_snapshot_together(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            rc = self._run(
                [
                    "--market-snapshot",
                    str(EXAMPLE_SNAPSHOT),
                    "--carry-from-snapshot",
                    "--simulate-carry",
                ],
                tmp,
            )
            self.assertEqual(rc, 2)
            # No artifacts should be written when validation fails.
            self.assertFalse((tmp / "capital_routing" / "daily_capital_plan.json").exists())

    def test_carry_from_snapshot_requires_snapshot_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            rc = self._run(["--carry-from-snapshot"], tmp)
            self.assertEqual(rc, 2)


class RunDailyCapitalPlanWithPortfolioTests(unittest.TestCase):
    def _run(self, extra_args: list[str], tmp: Path) -> int:
        argv = [
            "--as-of",
            "2026-05-12",
            "--monthly-contribution-usd",
            "200",
            "--artifacts-dir",
            str(tmp),
            *extra_args,
        ]
        return cli.main(argv)

    def test_portfolio_only_no_market_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            rc = self._run(["--portfolio-snapshot", str(EXAMPLE_PORTFOLIO)], tmp)
            self.assertEqual(rc, 0)
            plan = json.loads(
                (tmp / "capital_routing" / "daily_capital_plan.json").read_text(encoding="utf-8")
            )
            self.assertIs(plan["manual_review_only"], True)
            self.assertIs(plan["live_trading_enabled"], False)
            self.assertEqual(
                plan["portfolio_snapshot_id"], "manual-portfolio-example-2026-05-12"
            )
            # Without a market snapshot, only USD cash is valued -> total = 100.0
            self.assertEqual(plan["portfolio_total_value_usd"], 100.0)
            self.assertGreater(len(plan["portfolio_warnings"]), 0)
            self.assertFalse((tmp / "execution.plan").exists())
            self.assertFalse((tmp / "final_decision.json").exists())

            report = (tmp / "reports" / "daily_report.md").read_text(encoding="utf-8")
            self.assertIn("## Portfolio Snapshot", report)
            self.assertIn("manual-portfolio-example-2026-05-12", report)

    def test_portfolio_with_market_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            rc = self._run(
                [
                    "--market-snapshot",
                    str(EXAMPLE_SNAPSHOT),
                    "--portfolio-snapshot",
                    str(EXAMPLE_PORTFOLIO),
                ],
                tmp,
            )
            self.assertEqual(rc, 0)
            plan = json.loads(
                (tmp / "capital_routing" / "daily_capital_plan.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                plan["portfolio_snapshot_id"], "manual-portfolio-example-2026-05-12"
            )
            self.assertIsNotNone(plan["portfolio_total_value_usd"])
            self.assertGreater(plan["portfolio_total_value_usd"], 100.0)
            self.assertIn("market_snapshot", plan["metadata"])
            self.assertIn("portfolio_snapshot", plan["metadata"])
            self.assertTrue(plan["metadata"]["portfolio_snapshot"]["valuation_available"])
            # current_bucket_weights should sum to ~100 when valuation > 0
            weights = plan["current_bucket_weights"]
            self.assertAlmostEqual(sum(weights.values()), 100.0, places=4)
            # The example portfolio holds a large USD reserve that makes
            # cash_or_short_term_yield overweight (~24% vs 10% target). The
            # portfolio-aware allocator must NOT add to that overweight bucket.
            allocations = plan["long_term_allocations"]
            self.assertGreater(len(allocations), 0)
            total = sum(a["allocation_usd"] for a in allocations)
            self.assertAlmostEqual(total, 200.0, places=4)
            buckets = {a["bucket"] for a in allocations}
            self.assertNotIn("cash_or_short_term_yield", buckets)
            # Allocator rationales should mention "underweight" routing.
            self.assertTrue(
                any("underweight" in a.get("rationale", "").lower() for a in allocations)
            )

            report = (tmp / "reports" / "daily_report.md").read_text(encoding="utf-8")
            self.assertIn("## Portfolio Snapshot", report)
            self.assertIn("## Current Bucket Weights", report)
            self.assertIn("Target %", report)

    def test_portfolio_with_market_snapshot_and_carry_from_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            rc = self._run(
                [
                    "--market-snapshot",
                    str(EXAMPLE_SNAPSHOT),
                    "--portfolio-snapshot",
                    str(EXAMPLE_PORTFOLIO),
                    "--carry-from-snapshot",
                ],
                tmp,
            )
            self.assertEqual(rc, 0)
            plan = json.loads(
                (tmp / "capital_routing" / "daily_capital_plan.json").read_text(encoding="utf-8")
            )
            self.assertIs(plan["manual_review_only"], True)
            self.assertIs(plan["live_trading_enabled"], False)
            self.assertEqual(
                plan["portfolio_snapshot_id"], "manual-portfolio-example-2026-05-12"
            )
            self.assertEqual(
                plan["market_snapshot_id"], "manual-example-2026-05-12"
            )
            # No forbidden artifacts.
            self.assertFalse((tmp / "execution.plan").exists())
            self.assertFalse((tmp / "final_decision.json").exists())


if __name__ == "__main__":
    unittest.main()
