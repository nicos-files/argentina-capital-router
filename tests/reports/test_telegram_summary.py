import json
import tempfile
import unittest
from pathlib import Path

from src.reports.telegram_summary import (
    format_daily_plan_telegram_message,
    load_daily_plan_for_telegram,
    load_execution_comparison_for_telegram,
)


def _plan(**overrides):
    base = {
        "as_of": "2026-05-12",
        "manual_review_only": True,
        "live_trading_enabled": False,
        "monthly_long_term_contribution_usd": 200.0,
        "routing_decision": {
            "decision": "INVEST_DIRECT_LONG_TERM",
            "rationale": "No tactical opportunity.",
        },
        "long_term_allocations": [
            {"symbol": "SPY", "asset_class": "cedear", "allocation_usd": 133.60},
            {"symbol": "AAPL", "asset_class": "cedear", "allocation_usd": 22.13},
            {"symbol": "KO", "asset_class": "cedear", "allocation_usd": 22.13},
            {"symbol": "MELI", "asset_class": "cedear", "allocation_usd": 22.13},
        ],
        "skipped_allocations": [{"symbol": "X"}, {"symbol": "Y"}],
        "warnings": ["Snapshot completeness is partial."],
        "allocation_warnings": ["Allocation rounded."],
        "portfolio_total_value_usd": 170.83,
    }
    base.update(overrides)
    return base


def _comparison(**overrides):
    base = {
        "follow_rate_pct": 50.0,
        "matched_symbols": 0,
        "partial_symbols": 1,
        "missed_symbols": 1,
        "extra_symbols": 0,
    }
    base.update(overrides)
    return base


class FormatDailyPlanTelegramMessageTests(unittest.TestCase):
    def test_formats_basic_plan(self) -> None:
        msg = format_daily_plan_telegram_message(_plan())
        self.assertIn("Argentina Capital Router - 2026-05-12", msg)
        self.assertIn("Decision: INVEST_DIRECT_LONG_TERM", msg)
        self.assertIn("Manual review only. No live trading.", msg)
        self.assertIn("Monthly contribution: USD 200.00", msg)
        self.assertIn("Portfolio value: USD 170.83", msg)
        self.assertIn("1. SPY - USD 133.60", msg)
        self.assertIn("2. AAPL - USD 22.13", msg)

    def test_includes_skipped_count(self) -> None:
        msg = format_daily_plan_telegram_message(_plan())
        self.assertIn("Skipped: 2 below min trade", msg)

    def test_includes_warning_counts(self) -> None:
        msg = format_daily_plan_telegram_message(_plan())
        self.assertIn("Warnings: 1", msg)
        self.assertIn("Allocation warnings: 1", msg)

    def test_includes_execution_comparison(self) -> None:
        msg = format_daily_plan_telegram_message(
            _plan(), execution_comparison=_comparison()
        )
        self.assertIn("Execution comparison:", msg)
        self.assertIn("Follow rate: 50.0%", msg)
        self.assertIn(
            "Matched: 0 | Partial: 1 | Missed: 1 | Extra: 0", msg
        )

    def test_truncates_allocations_when_above_max(self) -> None:
        allocations = [
            {"symbol": f"SYM{i}", "asset_class": "cedear", "allocation_usd": 1.0}
            for i in range(12)
        ]
        msg = format_daily_plan_telegram_message(
            _plan(long_term_allocations=allocations), max_allocations=3
        )
        self.assertIn("1. SYM0 - USD 1.00", msg)
        self.assertIn("3. SYM2 - USD 1.00", msg)
        self.assertNotIn("4. SYM3", msg)
        self.assertIn("... and 9 more", msg)

    def test_message_never_contains_bot_token_string(self) -> None:
        # The formatter never receives credentials, so the message must be
        # token-free by construction. Pin the contract anyway.
        msg = format_daily_plan_telegram_message(_plan())
        self.assertNotIn("TELEGRAM_BOT_TOKEN", msg)
        self.assertNotIn(":AAAA", msg)
        self.assertNotIn("bot_token", msg.lower())

    def test_no_crypto_or_binance_wording(self) -> None:
        msg = format_daily_plan_telegram_message(_plan())
        lowered = msg.lower()
        self.assertNotIn("crypto", lowered)
        self.assertNotIn("binance", lowered)

    def test_stripped_markdown_in_dynamic_content(self) -> None:
        plan = _plan(
            long_term_allocations=[
                {
                    "symbol": "*BAD*",
                    "asset_class": "cedear",
                    "allocation_usd": 10.0,
                }
            ],
            warnings=["`unsafe` [link](x) markdown"],
        )
        msg = format_daily_plan_telegram_message(plan)
        # Bold/code/link characters in dynamic content must be stripped so
        # the message does not accidentally render as Markdown formatting.
        self.assertIn("1. BAD - USD 10.00", msg)
        self.assertNotIn("*BAD*", msg)
        for forbidden in ("*", "`", "[", "]"):
            for line in msg.splitlines():
                if line.startswith("Recommended manual review") or line.startswith("Argentina"):
                    continue
                self.assertNotIn(
                    forbidden,
                    line,
                    msg=f"forbidden char {forbidden!r} leaked into: {line!r}",
                )

    def test_underscores_in_decision_name_are_preserved(self) -> None:
        plan = _plan(
            routing_decision={
                "decision": "INVEST_DIRECT_LONG_TERM",
                "rationale": "",
            }
        )
        msg = format_daily_plan_telegram_message(plan)
        self.assertIn("Decision: INVEST_DIRECT_LONG_TERM", msg)


class LoaderTests(unittest.TestCase):
    def test_load_daily_plan_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            path = tmp / "plan.json"
            path.write_text(json.dumps(_plan()), encoding="utf-8")
            loaded = load_daily_plan_for_telegram(path)
            self.assertEqual(loaded["as_of"], "2026-05-12")
            self.assertEqual(
                loaded["routing_decision"]["decision"],
                "INVEST_DIRECT_LONG_TERM",
            )

    def test_load_execution_comparison_returns_none_for_no_path(self) -> None:
        self.assertIsNone(load_execution_comparison_for_telegram(None))

    def test_load_daily_plan_missing_file_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "not found"):
            load_daily_plan_for_telegram("/nonexistent/plan.json")

    def test_load_execution_comparison_invalid_json_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            path = tmp / "bad.json"
            path.write_text("not-json", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid JSON"):
                load_execution_comparison_for_telegram(path)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
