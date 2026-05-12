import json
import sys
import tempfile
import unittest
from pathlib import Path

from src.tools import run_daily_capital_plan as cli


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


if __name__ == "__main__":
    unittest.main()
