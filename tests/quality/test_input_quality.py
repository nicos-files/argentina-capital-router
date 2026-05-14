"""Tests for src/quality/input_quality.py.

Manual review only. No network. No broker. No live trading.
"""
from __future__ import annotations

import unittest

from src.manual_execution.execution_tracker import (
    ManualExecution,
    ManualExecutionLog,
)
from src.market_data.ar_symbols import ArgentinaAsset, load_ar_long_term_universe
from src.market_data.manual_snapshot import (
    FxRate,
    ManualMarketSnapshot,
    ManualQuote,
    RateInput,
)
from src.portfolio.portfolio_state import (
    CashBalance,
    ManualPortfolioSnapshot,
    PortfolioPosition,
)
from src.quality.input_quality import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    InputQualityIssue,
    InputQualityReport,
    combine_quality_reports,
    detect_placeholder_numeric_values,
    detect_todo_markers,
    validate_execution_log_quality,
    validate_market_snapshot_quality,
    validate_portfolio_snapshot_quality,
    validate_snapshot_dates,
    validate_symbols_in_universe,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _quote(
    symbol: str = "SPY",
    *,
    price: float = 10000.0,
    currency: str = "ARS",
    as_of: str = "2026-05-12",
) -> ManualQuote:
    return ManualQuote(
        symbol=symbol,
        asset_class="cedear",
        price=price,
        currency=currency,
        as_of=as_of,
    )


def _market_snapshot(
    *,
    as_of: str = "2026-05-12",
    quotes: dict[str, ManualQuote] | None = None,
    fx_rates: dict[str, FxRate] | None = None,
    rates: dict[str, RateInput] | None = None,
    completeness: str = "complete",
    warnings: tuple[str, ...] = (),
) -> ManualMarketSnapshot:
    if quotes is None:
        quotes = {"SPY": _quote("SPY")}
    if fx_rates is None:
        fx_rates = {
            "USDARS_MEP": FxRate(
                pair="USDARS_MEP", rate=1200.0, as_of=as_of
            )
        }
    if rates is None:
        # Populate the three "expected" rate keys so the default helper
        # produces a genuinely complete snapshot. Tests that want to
        # exercise the MISSING_RATE_INPUT path should pass ``rates={}``
        # explicitly.
        rates = {
            "money_market_monthly_pct": RateInput(
                key="money_market_monthly_pct", value=2.5, as_of=as_of
            ),
            "caucion_monthly_pct": RateInput(
                key="caucion_monthly_pct", value=2.8, as_of=as_of
            ),
            "expected_fx_devaluation_monthly_pct": RateInput(
                key="expected_fx_devaluation_monthly_pct",
                value=1.5,
                as_of=as_of,
            ),
        }
    return ManualMarketSnapshot(
        schema_version="1.0",
        snapshot_id="test",
        as_of=as_of,
        source="manual",
        manual_review_only=True,
        live_trading_enabled=False,
        data_frequency="1d",
        quotes=quotes,
        fx_rates=fx_rates,
        rates=rates,
        warnings=warnings,
        completeness=completeness,
    )


def _position(symbol: str = "SPY", *, quantity: float = 2.0) -> PortfolioPosition:
    return PortfolioPosition(
        symbol=symbol,
        asset_class="cedear",
        quantity=quantity,
        average_cost=9500.0,
        average_cost_currency="ARS",
        market="BYMA",
        bucket="core_global_equity",
    )


def _portfolio_snapshot(
    *,
    as_of: str = "2026-05-12",
    positions: tuple[PortfolioPosition, ...] = (),
    cash: tuple[CashBalance, ...] = (),
    completeness: str = "complete",
    warnings: tuple[str, ...] = (),
) -> ManualPortfolioSnapshot:
    if not positions:
        positions = (_position(),)
    return ManualPortfolioSnapshot(
        schema_version="1.0",
        snapshot_id="test",
        as_of=as_of,
        source="manual",
        base_currency="USD",
        manual_review_only=True,
        live_trading_enabled=False,
        cash=cash,
        positions=positions,
        warnings=warnings,
        completeness=completeness,
    )


def _execution_log(
    *,
    as_of: str = "2026-05-12",
    completeness: str = "complete",
    executions: tuple[ManualExecution, ...] = (),
) -> ManualExecutionLog:
    return ManualExecutionLog(
        schema_version="1.0",
        execution_log_id="test",
        as_of=as_of,
        manual_review_only=True,
        live_trading_enabled=False,
        source="manual",
        broker="test",
        base_currency="USD",
        notes="",
        executions=executions,
        warnings=(),
        completeness=completeness,
    )


def _universe() -> list[ArgentinaAsset]:
    """Use the real configured universe so the tests reflect production setup."""
    return load_ar_long_term_universe()


# ---------------------------------------------------------------------------
# Detector tests
# ---------------------------------------------------------------------------


class DetectTodoMarkersTests(unittest.TestCase):
    def test_detects_recursively_in_strings(self) -> None:
        data = {
            "quotes": [
                {"symbol": "SPY", "notes": "TODO: replace with real price"}
            ],
            "quality": {"warnings": ["template file - placeholder"]},
        }
        issues = detect_todo_markers(data)
        codes = {i.code for i in issues}
        self.assertEqual(codes, {"TODO_MARKER"})
        # Two distinct paths should be reported.
        paths = {i.path for i in issues}
        self.assertIn("quotes[0].notes", paths)
        self.assertIn("quality.warnings[0]", paths)

    def test_case_insensitive_match(self) -> None:
        issues = detect_todo_markers({"a": "Replace me"})
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].code, "TODO_MARKER")

    def test_returns_empty_when_clean(self) -> None:
        issues = detect_todo_markers({"a": "clean string", "b": 123})
        self.assertEqual(issues, [])

    def test_ignores_non_string_values(self) -> None:
        issues = detect_todo_markers({"a": 1.0, "b": True, "c": None})
        self.assertEqual(issues, [])


class DetectPlaceholderNumericValuesTests(unittest.TestCase):
    def test_market_quote_price_one_is_placeholder(self) -> None:
        data = {
            "quotes": [
                {"symbol": "SPY", "price": 1.0, "currency": "ARS"},
                {"symbol": "GGAL", "price": 4500.0, "currency": "ARS"},
            ]
        }
        issues = detect_placeholder_numeric_values(data, "market")
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].code, "PLACEHOLDER_VALUE")
        self.assertEqual(issues[0].symbol, "SPY")
        self.assertEqual(issues[0].path, "quotes[0].price")

    def test_market_fx_rate_one_is_placeholder(self) -> None:
        data = {"fx_rates": {"USDARS_MEP": {"rate": 1.0}}}
        issues = detect_placeholder_numeric_values(data, "market")
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].path, "fx_rates.USDARS_MEP.rate")

    def test_market_rates_all_zero_is_placeholder(self) -> None:
        data = {
            "rates": {
                "money_market_monthly_pct": {"value": 0.0},
                "caucion_monthly_pct": {"value": 0.0},
            }
        }
        issues = detect_placeholder_numeric_values(data, "market")
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].path, "rates")

    def test_market_rates_one_nonzero_is_not_placeholder(self) -> None:
        data = {
            "rates": {
                "money_market_monthly_pct": {"value": 0.0},
                "caucion_monthly_pct": {"value": 2.5},
            }
        }
        self.assertEqual(
            detect_placeholder_numeric_values(data, "market"), []
        )

    def test_portfolio_position_quantity_and_cost_one_is_placeholder(self) -> None:
        data = {
            "positions": [
                {"symbol": "SPY", "quantity": 1.0, "average_cost": 1.0},
                {"symbol": "AAPL", "quantity": 1.0, "average_cost": 5.0},
            ]
        }
        issues = detect_placeholder_numeric_values(data, "portfolio")
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].symbol, "SPY")

    def test_portfolio_cash_one_is_placeholder(self) -> None:
        data = {"cash": [{"currency": "USD", "amount": 1.0}]}
        issues = detect_placeholder_numeric_values(data, "portfolio")
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].path, "cash[0].amount")

    def test_unknown_snapshot_kind_returns_empty(self) -> None:
        self.assertEqual(
            detect_placeholder_numeric_values({"quotes": []}, "unknown"), []
        )


# ---------------------------------------------------------------------------
# Snapshot-level validator tests
# ---------------------------------------------------------------------------


class SnapshotDateMismatchTests(unittest.TestCase):
    def test_market_date_mismatch(self) -> None:
        snapshot = _market_snapshot(as_of="2026-05-11")
        issues = validate_snapshot_dates(
            "2026-05-12", market_snapshot=snapshot
        )
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].code, "SNAPSHOT_DATE_MISMATCH")

    def test_no_expected_date_returns_empty(self) -> None:
        snapshot = _market_snapshot(as_of="2026-05-11")
        self.assertEqual(
            validate_snapshot_dates(None, market_snapshot=snapshot), []
        )

    def test_execution_executed_at_prefix_match(self) -> None:
        execution = ManualExecution(
            execution_id="e1",
            plan_id="p1",
            symbol="SPY",
            asset_class="cedear",
            side="buy",
            quantity=1.0,
            price=10000.0,
            price_currency="ARS",
            fees=0.0,
            fees_currency="ARS",
            executed_at="2026-05-12T15:30:00-03:00",
            broker="manual",
        )
        log = _execution_log(executions=(execution,))
        issues = validate_snapshot_dates("2026-05-12", execution_log=log)
        self.assertEqual(issues, [])

    def test_execution_executed_at_mismatch(self) -> None:
        execution = ManualExecution(
            execution_id="e1",
            plan_id="p1",
            symbol="SPY",
            asset_class="cedear",
            side="buy",
            quantity=1.0,
            price=10000.0,
            price_currency="ARS",
            fees=0.0,
            fees_currency="ARS",
            executed_at="2026-05-11T15:30:00-03:00",
            broker="manual",
        )
        log = _execution_log(executions=(execution,))
        issues = validate_snapshot_dates("2026-05-12", execution_log=log)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].symbol, "SPY")


class SymbolsInUniverseTests(unittest.TestCase):
    def test_unknown_market_symbol(self) -> None:
        snapshot = _market_snapshot(
            quotes={"FAKE": _quote("FAKE"), "SPY": _quote("SPY")}
        )
        issues = validate_symbols_in_universe(
            market_snapshot=snapshot,
            portfolio_snapshot=None,
            universe_assets=_universe(),
        )
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].symbol, "FAKE")
        self.assertEqual(issues[0].code, "UNKNOWN_SYMBOL")

    def test_unknown_portfolio_symbol(self) -> None:
        snapshot = _portfolio_snapshot(positions=(_position("FAKE"),))
        issues = validate_symbols_in_universe(
            market_snapshot=None,
            portfolio_snapshot=snapshot,
            universe_assets=_universe(),
        )
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].symbol, "FAKE")

    def test_all_known_symbols_pass(self) -> None:
        market = _market_snapshot(quotes={"SPY": _quote("SPY")})
        portfolio = _portfolio_snapshot(positions=(_position("SPY"),))
        self.assertEqual(
            validate_symbols_in_universe(
                market_snapshot=market,
                portfolio_snapshot=portfolio,
                universe_assets=_universe(),
            ),
            [],
        )


class MarketSnapshotQualityTests(unittest.TestCase):
    def test_clean_market_snapshot_has_no_warnings(self) -> None:
        report = validate_market_snapshot_quality(
            raw_market_data={"quotes": [], "fx_rates": {}, "rates": {}},
            market_snapshot=_market_snapshot(),
            expected_date="2026-05-12",
            universe_assets=_universe(),
            strict=False,
        )
        self.assertTrue(report.ok)
        self.assertEqual(report.warnings_count, 0)

    def test_missing_usdars_mep_when_ars_quote_present(self) -> None:
        market = _market_snapshot(
            quotes={"SPY": _quote("SPY", currency="ARS")},
            fx_rates={},  # explicitly missing USDARS_MEP
        )
        report = validate_market_snapshot_quality(
            raw_market_data=None,
            market_snapshot=market,
            expected_date="2026-05-12",
            universe_assets=_universe(),
            strict=False,
        )
        codes = [i.code for i in report.issues]
        self.assertIn("MISSING_REQUIRED_FX", codes)

    def test_incomplete_snapshot_is_warning_in_default_mode(self) -> None:
        market = _market_snapshot(completeness="partial")
        report = validate_market_snapshot_quality(
            raw_market_data=None,
            market_snapshot=market,
            strict=False,
        )
        self.assertTrue(report.ok)
        self.assertEqual(report.warnings_count, 1)
        self.assertEqual(report.issues[0].code, "INCOMPLETE_SNAPSHOT")

    # ------------------------------------------------------------------
    # FX / rate input quality
    # ------------------------------------------------------------------

    def test_fx_rate_equal_to_one_is_flagged_as_placeholder(self) -> None:
        report = validate_market_snapshot_quality(
            raw_market_data={
                "fx_rates": {
                    "USDARS_MEP": {"rate": 1.0},
                }
            },
            market_snapshot=_market_snapshot(),
            strict=False,
        )
        codes = [i.code for i in report.issues]
        self.assertIn("PLACEHOLDER_VALUE", codes)

    def test_fx_rate_below_or_equal_zero_is_rejected_at_load(self) -> None:
        # The loader refuses to parse fx_rates with rate <= 0 so invalid
        # values cannot reach validate_market_snapshot_quality. Document
        # that behaviour here as a regression guard.
        import json
        import tempfile
        from pathlib import Path

        from src.market_data.manual_snapshot import load_manual_market_snapshot

        def _write_and_load(rate: float) -> None:
            with tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp) / "m.json"
                p.write_text(
                    json.dumps(
                        {
                            "schema_version": "1.0",
                            "snapshot_id": "bad",
                            "as_of": "2026-05-12",
                            "source": "manual",
                            "manual_review_only": True,
                            "live_trading_enabled": False,
                            "data_frequency": "1d",
                            "quotes": [],
                            "fx_rates": {
                                "USDARS_MEP": {
                                    "rate": rate,
                                    "as_of": "2026-05-12",
                                }
                            },
                            "rates": {},
                            "completeness": "complete",
                        }
                    )
                )
                load_manual_market_snapshot(p)

        with self.assertRaises(ValueError):
            _write_and_load(0.0)
        with self.assertRaises(ValueError):
            _write_and_load(-1.0)

    def test_all_zero_rate_inputs_flagged_as_placeholder(self) -> None:
        report = validate_market_snapshot_quality(
            raw_market_data={
                "rates": {
                    "money_market_monthly_pct": {"value": 0.0},
                    "caucion_monthly_pct": {"value": 0.0},
                    "expected_fx_devaluation_monthly_pct": {"value": 0.0},
                }
            },
            market_snapshot=_market_snapshot(),
            strict=False,
        )
        codes = [i.code for i in report.issues]
        self.assertIn("PLACEHOLDER_VALUE", codes)

    def test_missing_expected_rate_inputs_each_flagged(self) -> None:
        # Empty rates -> one MISSING_RATE_INPUT per expected key.
        market = _market_snapshot(rates={})
        report = validate_market_snapshot_quality(
            raw_market_data=None,
            market_snapshot=market,
            strict=False,
        )
        missing_rate_issues = [
            i for i in report.issues if i.code == "MISSING_RATE_INPUT"
        ]
        self.assertEqual(len(missing_rate_issues), 3)
        missing_paths = sorted(i.path for i in missing_rate_issues)
        self.assertEqual(
            missing_paths,
            [
                "rates.caucion_monthly_pct",
                "rates.expected_fx_devaluation_monthly_pct",
                "rates.money_market_monthly_pct",
            ],
        )

    def test_missing_rate_input_is_not_promoted_to_error_in_strict_mode(
        self,
    ) -> None:
        # Strict mode promotes INCOMPLETE_SNAPSHOT to ERROR (since the
        # snapshot is partial), but the per-key MISSING_RATE_INPUT stays
        # a WARNING so the user still sees which keys are missing.
        market = _market_snapshot(rates={}, completeness="complete")
        report = validate_market_snapshot_quality(
            raw_market_data=None,
            market_snapshot=market,
            strict=True,
        )
        codes_by_severity = {
            (i.severity, i.code) for i in report.issues
        }
        self.assertIn(("WARNING", "MISSING_RATE_INPUT"), codes_by_severity)
        for sev, code in codes_by_severity:
            if code == "MISSING_RATE_INPUT":
                self.assertEqual(sev, "WARNING")

    def test_valid_fx_and_rates_pass_strict_quality(self) -> None:
        report = validate_market_snapshot_quality(
            raw_market_data={"quotes": [], "fx_rates": {}, "rates": {}},
            market_snapshot=_market_snapshot(),
            expected_date="2026-05-12",
            universe_assets=_universe(),
            strict=True,
        )
        self.assertTrue(report.ok)
        self.assertEqual(report.errors_count, 0)


class PortfolioSnapshotQualityTests(unittest.TestCase):
    def test_missing_position_price_when_market_present(self) -> None:
        market = _market_snapshot(quotes={"SPY": _quote("SPY")})
        portfolio = _portfolio_snapshot(
            positions=(_position("SPY"), _position("AAPL"))
        )
        report = validate_portfolio_snapshot_quality(
            raw_portfolio_data=None,
            portfolio_snapshot=portfolio,
            market_snapshot=market,
            universe_assets=_universe(),
            strict=False,
        )
        missing = [i for i in report.issues if i.code == "MISSING_POSITION_PRICE"]
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0].symbol, "AAPL")

    def test_ars_cash_without_usdars_mep_flags_fx(self) -> None:
        market = _market_snapshot(
            quotes={"SPY": _quote("SPY", currency="ARS")}, fx_rates={}
        )
        portfolio = _portfolio_snapshot(
            cash=(CashBalance(currency="ARS", amount=1000.0, bucket="cash"),),
            positions=(_position("SPY"),),
        )
        report = validate_portfolio_snapshot_quality(
            raw_portfolio_data=None,
            portfolio_snapshot=portfolio,
            market_snapshot=market,
            universe_assets=_universe(),
            strict=False,
        )
        codes = [i.code for i in report.issues]
        self.assertIn("MISSING_REQUIRED_FX", codes)

    def test_no_market_snapshot_emits_info_only(self) -> None:
        report = validate_portfolio_snapshot_quality(
            raw_portfolio_data=None,
            portfolio_snapshot=_portfolio_snapshot(),
            market_snapshot=None,
            universe_assets=_universe(),
            strict=False,
        )
        self.assertTrue(report.ok)
        self.assertEqual(report.warnings_count, 0)
        self.assertTrue(
            any(i.code == "MARKET_SNAPSHOT_NOT_PROVIDED" for i in report.issues)
        )


class ExecutionLogQualityTests(unittest.TestCase):
    def test_incomplete_log_is_warning(self) -> None:
        log = _execution_log(completeness="partial")
        report = validate_execution_log_quality(
            raw_execution_data=None,
            execution_log=log,
            strict=False,
        )
        self.assertTrue(report.ok)
        self.assertEqual(report.warnings_count, 1)

    def test_strict_promotes_incomplete_to_error(self) -> None:
        log = _execution_log(completeness="partial")
        report = validate_execution_log_quality(
            raw_execution_data=None,
            execution_log=log,
            strict=True,
        )
        self.assertFalse(report.ok)
        self.assertEqual(report.errors_count, 1)


# ---------------------------------------------------------------------------
# Strict promotion + combine
# ---------------------------------------------------------------------------


class CombineAndStrictPromotionTests(unittest.TestCase):
    def test_strict_promotes_todo_warning_to_error(self) -> None:
        market = _market_snapshot()
        permissive = validate_market_snapshot_quality(
            raw_market_data={"quotes": [{"notes": "TODO replace"}]},
            market_snapshot=market,
            strict=False,
        )
        self.assertTrue(permissive.ok)
        self.assertEqual(permissive.warnings_count, 1)
        self.assertEqual(permissive.errors_count, 0)

        strict = validate_market_snapshot_quality(
            raw_market_data={"quotes": [{"notes": "TODO replace"}]},
            market_snapshot=market,
            strict=True,
        )
        self.assertFalse(strict.ok)
        self.assertEqual(strict.errors_count, 1)

    def test_strict_promotes_date_mismatch(self) -> None:
        market = _market_snapshot(as_of="2026-05-11")
        report = validate_market_snapshot_quality(
            raw_market_data=None,
            market_snapshot=market,
            expected_date="2026-05-12",
            strict=True,
        )
        self.assertFalse(report.ok)
        codes = {i.code for i in report.issues if i.severity == SEVERITY_ERROR}
        self.assertIn("SNAPSHOT_DATE_MISMATCH", codes)

    def test_strict_does_not_promote_info(self) -> None:
        portfolio = _portfolio_snapshot()
        report = validate_portfolio_snapshot_quality(
            raw_portfolio_data=None,
            portfolio_snapshot=portfolio,
            market_snapshot=None,
            universe_assets=_universe(),
            strict=True,
        )
        # MARKET_SNAPSHOT_NOT_PROVIDED is INFO and must remain INFO.
        infos = [i for i in report.issues if i.code == "MARKET_SNAPSHOT_NOT_PROVIDED"]
        self.assertEqual(len(infos), 1)
        self.assertEqual(infos[0].severity, "INFO")

    def test_combine_counts_errors_and_warnings(self) -> None:
        r1 = InputQualityReport(
            ok=True,
            strict=False,
            issues=(
                InputQualityIssue(
                    severity=SEVERITY_WARNING,
                    code="TODO_MARKER",
                    message="x",
                ),
            ),
        )
        r2 = InputQualityReport(
            ok=False,
            strict=False,
            issues=(
                InputQualityIssue(
                    severity=SEVERITY_ERROR, code="X", message="boom"
                ),
            ),
        )
        combined = combine_quality_reports(r1, r2, strict=False)
        self.assertFalse(combined.ok)
        self.assertEqual(combined.errors_count, 1)
        self.assertEqual(combined.warnings_count, 1)

    def test_combine_strict_promotes_across_reports(self) -> None:
        r1 = InputQualityReport(
            ok=True,
            strict=False,
            issues=(
                InputQualityIssue(
                    severity=SEVERITY_WARNING,
                    code="TODO_MARKER",
                    message="x",
                ),
                InputQualityIssue(
                    severity=SEVERITY_WARNING,
                    code="UNKNOWN_SYMBOL",
                    message="y",
                ),
            ),
        )
        r2 = InputQualityReport(
            ok=True,
            strict=False,
            issues=(
                InputQualityIssue(
                    severity=SEVERITY_WARNING,
                    code="MISSING_POSITION_PRICE",
                    message="z",
                ),
            ),
        )
        combined = combine_quality_reports(r1, r2, strict=True)
        self.assertFalse(combined.ok)
        self.assertEqual(combined.errors_count, 3)
        self.assertEqual(combined.warnings_count, 0)

    def test_to_dict_shape(self) -> None:
        report = InputQualityReport(
            ok=False,
            strict=True,
            issues=(
                InputQualityIssue(
                    severity=SEVERITY_ERROR,
                    code="TODO_MARKER",
                    message="m",
                    path="quotes[0].notes",
                    symbol="SPY",
                ),
            ),
        )
        data = report.to_dict()
        self.assertEqual(data["ok"], False)
        self.assertEqual(data["strict"], True)
        self.assertEqual(data["errors_count"], 1)
        self.assertEqual(data["warnings_count"], 0)
        self.assertEqual(data["infos_count"], 0)
        self.assertEqual(data["issues"][0]["code"], "TODO_MARKER")
        self.assertEqual(data["issues"][0]["path"], "quotes[0].notes")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
