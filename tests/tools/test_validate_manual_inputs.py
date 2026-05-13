import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from src.tools import validate_manual_inputs as cli


REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_MARKET = (
    REPO_ROOT / "config" / "data_inputs" / "manual_market_snapshot.example.json"
)
EXAMPLE_PORTFOLIO = (
    REPO_ROOT / "config" / "portfolio" / "manual_portfolio_snapshot.example.json"
)


def _scrub_notes(obj):
    """Recursively replace any ``notes`` string with an empty string.

    The committed example snapshots intentionally describe themselves as
    placeholders ("Example placeholder ...", "Replace with real ..."), which
    is desirable in production but trips the TODO_MARKER quality check.
    Tests that aim to pass ``--strict`` need a copy with those strings
    removed.
    """
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


def _make_complete_market(tmp: Path) -> Path:
    raw = json.loads(EXAMPLE_MARKET.read_text(encoding="utf-8"))
    raw["quality"] = {"warnings": [], "completeness": "complete"}
    _scrub_notes(raw)
    out = tmp / "market_complete.json"
    out.write_text(json.dumps(raw), encoding="utf-8")
    return out


def _make_complete_portfolio(
    tmp: Path,
    *,
    drop_unknown_positions: bool = True,
) -> Path:
    raw = json.loads(EXAMPLE_PORTFOLIO.read_text(encoding="utf-8"))
    if drop_unknown_positions:
        # Example market snapshot only prices SPY + GGAL, so drop AAPL so the
        # portfolio is fully priced under strict checks.
        raw["positions"] = [
            p for p in raw["positions"] if p["symbol"] in {"SPY", "GGAL"}
        ]
    raw["quality"] = {"warnings": [], "completeness": "complete"}
    _scrub_notes(raw)
    out = tmp / "portfolio_complete.json"
    out.write_text(json.dumps(raw), encoding="utf-8")
    return out


def _write_template_market(tmp: Path) -> Path:
    """Write the canonical untouched market template to ``tmp``."""
    src = (
        REPO_ROOT
        / "config"
        / "data_inputs"
        / "manual_market_snapshot.template.json"
    )
    out = tmp / "market_template.json"
    out.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return out


def _write_template_portfolio(tmp: Path) -> Path:
    src = (
        REPO_ROOT
        / "config"
        / "portfolio"
        / "manual_portfolio_snapshot.template.json"
    )
    out = tmp / "portfolio_template.json"
    out.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return out


class ValidateManualInputsTests(unittest.TestCase):
    def _run(self, args: list[str]) -> tuple[int, str]:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.main(args)
        return rc, buf.getvalue()

    def test_market_only_example_exits_zero(self) -> None:
        rc, out = self._run(["--market-snapshot", str(EXAMPLE_MARKET)])
        self.assertEqual(rc, 0)
        self.assertIn("Validation status: valid", out)
        self.assertIn("Manual review only", out)

    def test_portfolio_only_example_exits_zero(self) -> None:
        rc, out = self._run(["--portfolio-snapshot", str(EXAMPLE_PORTFOLIO)])
        self.assertEqual(rc, 0)
        self.assertIn("Validation status: valid", out)

    def test_both_examples_exit_zero(self) -> None:
        rc, out = self._run(
            [
                "--market-snapshot",
                str(EXAMPLE_MARKET),
                "--portfolio-snapshot",
                str(EXAMPLE_PORTFOLIO),
            ]
        )
        self.assertEqual(rc, 0)
        self.assertIn("Validation status: valid", out)
        # Valuation block must be present when both snapshots are given.
        self.assertIn("Valuation:", out)

    def test_json_output_is_parseable(self) -> None:
        rc, out = self._run(
            [
                "--market-snapshot",
                str(EXAMPLE_MARKET),
                "--portfolio-snapshot",
                str(EXAMPLE_PORTFOLIO),
                "--json",
            ]
        )
        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertEqual(payload["status"], "valid")
        self.assertIs(payload["manual_review_only"], True)
        self.assertIs(payload["live_trading_enabled"], False)
        self.assertIn("market", payload)
        self.assertIn("portfolio", payload)
        self.assertIn("valuation", payload)
        self.assertIsInstance(
            payload["valuation"]["total_value_usd"], (int, float)
        )

    def test_strict_mode_fails_on_partial_completeness(self) -> None:
        rc, out = self._run(
            [
                "--market-snapshot",
                str(EXAMPLE_MARKET),
                "--portfolio-snapshot",
                str(EXAMPLE_PORTFOLIO),
                "--strict",
            ]
        )
        self.assertEqual(rc, 1)
        self.assertIn("Strict-mode failures", out)

    def test_strict_mode_passes_with_complete_snapshots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            market = _make_complete_market(tmp)
            portfolio = _make_complete_portfolio(tmp)
            rc, out = self._run(
                [
                    "--market-snapshot",
                    str(market),
                    "--portfolio-snapshot",
                    str(portfolio),
                    "--strict",
                ]
            )
            self.assertEqual(rc, 0, msg=out)

    def test_strict_mode_fails_when_position_missing_price(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            market = _make_complete_market(tmp)
            # Keep AAPL even though the market snapshot has no AAPL quote.
            portfolio = _make_complete_portfolio(
                tmp, drop_unknown_positions=False
            )
            rc, out = self._run(
                [
                    "--market-snapshot",
                    str(market),
                    "--portfolio-snapshot",
                    str(portfolio),
                    "--strict",
                ]
            )
            self.assertEqual(rc, 1)
            self.assertIn("missing price", out)

    def test_invalid_path_returns_invalid(self) -> None:
        rc, out = self._run(
            ["--market-snapshot", "/does/not/exist/market.json"]
        )
        self.assertEqual(rc, 1)
        self.assertIn("market snapshot invalid", out)

    def test_no_snapshot_args_returns_usage_error(self) -> None:
        rc, out = self._run([])
        self.assertEqual(rc, 2)
        self.assertIn("at least one", out)

    def test_valuation_summary_reports_total_value_usd(self) -> None:
        rc, out = self._run(
            [
                "--market-snapshot",
                str(EXAMPLE_MARKET),
                "--portfolio-snapshot",
                str(EXAMPLE_PORTFOLIO),
            ]
        )
        self.assertEqual(rc, 0)
        self.assertIn("total_value_usd:", out)

    def test_non_strict_template_passes_with_quality_warnings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            market = _write_template_market(tmp)
            portfolio = _write_template_portfolio(tmp)
            rc, out = self._run(
                [
                    "--market-snapshot",
                    str(market),
                    "--portfolio-snapshot",
                    str(portfolio),
                    "--json",
                ]
            )
            self.assertEqual(rc, 0, msg=out)
            payload = json.loads(out)
            self.assertEqual(payload["status"], "valid")
            self.assertIn("quality", payload)
            quality = payload["quality"]
            self.assertTrue(quality["ok"])
            self.assertFalse(quality["strict"])
            self.assertGreater(quality["warnings_count"], 0)
            codes = {issue["code"] for issue in quality["issues"]}
            self.assertIn("TODO_MARKER", codes)
            self.assertIn("PLACEHOLDER_VALUE", codes)

    def test_strict_fails_on_template_todos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            market = _write_template_market(tmp)
            portfolio = _write_template_portfolio(tmp)
            rc, out = self._run(
                [
                    "--market-snapshot",
                    str(market),
                    "--portfolio-snapshot",
                    str(portfolio),
                    "--strict",
                    "--json",
                ]
            )
            self.assertEqual(rc, 1)
            payload = json.loads(out)
            self.assertEqual(payload["status"], "strict_failed")
            quality = payload["quality"]
            self.assertFalse(quality["ok"])
            self.assertTrue(quality["strict"])
            self.assertGreater(quality["errors_count"], 0)
            codes = {issue["code"] for issue in quality["issues"]}
            self.assertIn("TODO_MARKER", codes)

    def test_strict_expected_date_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            market = _make_complete_market(tmp)
            portfolio = _make_complete_portfolio(tmp)
            rc, out = self._run(
                [
                    "--market-snapshot",
                    str(market),
                    "--portfolio-snapshot",
                    str(portfolio),
                    "--expected-date",
                    "2026-06-01",
                    "--strict",
                    "--json",
                ]
            )
            self.assertEqual(rc, 1)
            payload = json.loads(out)
            self.assertEqual(payload["status"], "strict_failed")
            codes = {issue["code"] for issue in payload["quality"]["issues"]}
            self.assertIn("SNAPSHOT_DATE_MISMATCH", codes)

    def test_strict_unknown_symbol_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            market_raw = json.loads(
                EXAMPLE_MARKET.read_text(encoding="utf-8")
            )
            # Inject a symbol that is not in the configured universe.
            market_raw["quotes"].append(
                {
                    "symbol": "FAKECORP",
                    "asset_class": "cedear",
                    "price": 1500.0,
                    "currency": "ARS",
                    "as_of": market_raw["as_of"],
                    "provider": "manual",
                    "delayed": True,
                    "notes": "",
                }
            )
            market_raw["quality"] = {
                "warnings": [],
                "completeness": "complete",
            }
            _scrub_notes(market_raw)
            market = tmp / "market_with_unknown.json"
            market.write_text(json.dumps(market_raw), encoding="utf-8")
            rc, out = self._run(
                ["--market-snapshot", str(market), "--strict", "--json"]
            )
            self.assertEqual(rc, 1)
            payload = json.loads(out)
            codes = {issue["code"] for issue in payload["quality"]["issues"]}
            self.assertIn("UNKNOWN_SYMBOL", codes)

    def test_strict_cleaned_snapshot_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            market = _make_complete_market(tmp)
            portfolio = _make_complete_portfolio(tmp)
            rc, out = self._run(
                [
                    "--market-snapshot",
                    str(market),
                    "--portfolio-snapshot",
                    str(portfolio),
                    "--expected-date",
                    "2026-05-12",
                    "--strict",
                    "--json",
                ]
            )
            self.assertEqual(rc, 0, msg=out)
            payload = json.loads(out)
            self.assertEqual(payload["status"], "valid")
            self.assertTrue(payload["quality"]["ok"])
            self.assertEqual(payload["quality"]["errors_count"], 0)

    def test_json_includes_quality_block(self) -> None:
        rc, out = self._run(
            [
                "--market-snapshot",
                str(EXAMPLE_MARKET),
                "--portfolio-snapshot",
                str(EXAMPLE_PORTFOLIO),
                "--json",
            ]
        )
        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertIn("quality", payload)
        quality = payload["quality"]
        for key in (
            "ok",
            "strict",
            "errors_count",
            "warnings_count",
            "infos_count",
            "issues",
        ):
            self.assertIn(key, quality)

    def test_validator_does_not_write_forbidden_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            # Validator is read-only by design; running it should not produce
            # any file under an unrelated working dir.
            rc, _ = self._run(
                [
                    "--market-snapshot",
                    str(EXAMPLE_MARKET),
                    "--portfolio-snapshot",
                    str(EXAMPLE_PORTFOLIO),
                ]
            )
            self.assertEqual(rc, 0)
            self.assertFalse((tmp / "execution.plan").exists())
            self.assertFalse((tmp / "final_decision.json").exists())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
