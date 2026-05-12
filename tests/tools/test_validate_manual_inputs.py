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


def _make_complete_market(tmp: Path) -> Path:
    raw = json.loads(EXAMPLE_MARKET.read_text(encoding="utf-8"))
    raw["quality"] = {"warnings": [], "completeness": "complete"}
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
    out = tmp / "portfolio_complete.json"
    out.write_text(json.dumps(raw), encoding="utf-8")
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
