import json
import tempfile
import unittest
from pathlib import Path

from src.market_data.manual_snapshot import load_manual_market_snapshot
from src.portfolio.portfolio_state import load_manual_portfolio_snapshot
from src.portfolio.portfolio_valuation import (
    MISSING_FX,
    MISSING_PRICE,
    NO_MARKET_SNAPSHOT,
    PRICED,
    UNSUPPORTED_CURRENCY,
    get_usdars_rate,
    value_portfolio,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_PORTFOLIO = (
    REPO_ROOT / "config" / "portfolio" / "manual_portfolio_snapshot.example.json"
)
EXAMPLE_MARKET = (
    REPO_ROOT / "config" / "data_inputs" / "manual_market_snapshot.example.json"
)


class GetUsdarsRateTests(unittest.TestCase):
    def test_returns_none_when_snapshot_missing(self) -> None:
        self.assertIsNone(get_usdars_rate(None))

    def test_returns_rate_from_example(self) -> None:
        market = load_manual_market_snapshot(EXAMPLE_MARKET)
        self.assertEqual(get_usdars_rate(market), 1200.0)

    def test_returns_none_when_pair_absent(self) -> None:
        market = load_manual_market_snapshot(EXAMPLE_MARKET)
        self.assertIsNone(get_usdars_rate(market, key="EURUSD"))


class ValuePortfolioWithMarketSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.portfolio = load_manual_portfolio_snapshot(EXAMPLE_PORTFOLIO)
        self.market = load_manual_market_snapshot(EXAMPLE_MARKET)

    def test_values_known_positions_in_usd(self) -> None:
        valuation = value_portfolio(self.portfolio, market_snapshot=self.market)
        by_symbol = {p.symbol: p for p in valuation.positions}
        # SPY: 2 * 10000 ARS / 1200 = 16.666...
        self.assertAlmostEqual(by_symbol["SPY"].market_value, 2 * 10000 / 1200, places=6)
        self.assertEqual(by_symbol["SPY"].valuation_status, PRICED)
        # GGAL: 3 * 5000 ARS / 1200 = 12.5
        self.assertAlmostEqual(by_symbol["GGAL"].market_value, 3 * 5000 / 1200, places=6)
        self.assertEqual(by_symbol["GGAL"].valuation_status, PRICED)

    def test_missing_price_for_aapl_creates_warning_not_failure(self) -> None:
        valuation = value_portfolio(self.portfolio, market_snapshot=self.market)
        by_symbol = {p.symbol: p for p in valuation.positions}
        # AAPL not in example market snapshot
        self.assertIn("AAPL", by_symbol)
        self.assertEqual(by_symbol["AAPL"].valuation_status, MISSING_PRICE)
        self.assertIsNone(by_symbol["AAPL"].market_value)
        self.assertTrue(any("AAPL" in w for w in valuation.warnings))

    def test_values_usd_cash_directly_and_ars_cash_via_fx(self) -> None:
        valuation = value_portfolio(self.portfolio, market_snapshot=self.market)
        by_currency = {c.currency: c for c in valuation.cash}
        self.assertEqual(by_currency["USD"].value_usd, 100.0)
        self.assertAlmostEqual(by_currency["ARS"].value_usd, 50000.0 / 1200.0, places=6)
        for c in valuation.cash:
            self.assertEqual(c.valuation_status, PRICED)

    def test_total_value_and_bucket_weights(self) -> None:
        valuation = value_portfolio(self.portfolio, market_snapshot=self.market)
        # SPY (16.6667) + GGAL (12.5) + USD cash 100 + ARS cash (41.6667)
        expected = 2 * 10000 / 1200 + 3 * 5000 / 1200 + 100.0 + 50000.0 / 1200.0
        self.assertAlmostEqual(valuation.total_value_usd, expected, places=6)
        self.assertGreater(len(valuation.bucket_weights), 0)
        total_pct = sum(valuation.bucket_weights.values())
        self.assertAlmostEqual(total_pct, 100.0, places=4)


class ValuePortfolioWithoutMarketSnapshotTests(unittest.TestCase):
    def test_no_market_snapshot_marks_positions_unpriced(self) -> None:
        portfolio = load_manual_portfolio_snapshot(EXAMPLE_PORTFOLIO)
        valuation = value_portfolio(portfolio, market_snapshot=None)
        for pos in valuation.positions:
            self.assertEqual(pos.valuation_status, NO_MARKET_SNAPSHOT)
            self.assertIsNone(pos.market_value)
        # USD cash still values directly; ARS cash should be MISSING_FX
        by_currency = {c.currency: c for c in valuation.cash}
        self.assertEqual(by_currency["USD"].value_usd, 100.0)
        self.assertEqual(by_currency["USD"].valuation_status, PRICED)
        self.assertEqual(by_currency["ARS"].valuation_status, MISSING_FX)
        self.assertIsNone(by_currency["ARS"].value_usd)
        # Total = 100 USD (only USD cash). Bucket weights computed only for that.
        self.assertEqual(valuation.total_value_usd, 100.0)
        self.assertAlmostEqual(sum(valuation.bucket_weights.values()), 100.0, places=4)
        self.assertTrue(any("no market snapshot" in w.lower() for w in valuation.warnings))


class ValuePortfolioMissingFxTests(unittest.TestCase):
    def test_market_snapshot_without_usdars_warns(self) -> None:
        # Build a market snapshot without USDARS_MEP by removing it from the example.
        with tempfile.TemporaryDirectory() as tmp_dir:
            payload = json.loads(EXAMPLE_MARKET.read_text(encoding="utf-8"))
            payload["fx_rates"].pop("USDARS_MEP")
            path = Path(tmp_dir) / "market.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            market = load_manual_market_snapshot(path)

        portfolio = load_manual_portfolio_snapshot(EXAMPLE_PORTFOLIO)
        valuation = value_portfolio(portfolio, market_snapshot=market)
        by_symbol = {p.symbol: p for p in valuation.positions}
        # SPY priced in ARS, but no USDARS_MEP -> MISSING_FX
        self.assertEqual(by_symbol["SPY"].valuation_status, MISSING_FX)
        self.assertIsNone(by_symbol["SPY"].market_value)
        # ARS cash also MISSING_FX
        by_currency = {c.currency: c for c in valuation.cash}
        self.assertEqual(by_currency["ARS"].valuation_status, MISSING_FX)


if __name__ == "__main__":
    unittest.main()
