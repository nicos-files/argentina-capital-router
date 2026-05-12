import copy
import json
import tempfile
import unittest
from pathlib import Path

from src.market_data.ar_providers import StaticArgentinaMarketDataProvider
from src.market_data.manual_snapshot import (
    get_fx_rate,
    get_rate_input,
    load_manual_market_snapshot,
    normalize_fx_pair,
    snapshot_to_static_provider,
    summarize_snapshot,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_PATH = (
    REPO_ROOT / "config" / "data_inputs" / "manual_market_snapshot.example.json"
)


def _example_payload() -> dict:
    return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))


def _write_tmp(payload: dict, tmp_dir: Path) -> Path:
    path = tmp_dir / "snapshot.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class NormalizeFxPairTests(unittest.TestCase):
    def test_examples(self) -> None:
        self.assertEqual(normalize_fx_pair("usdars mep"), "USDARS_MEP")
        self.assertEqual(normalize_fx_pair("USD/ARS CCL"), "USD_ARS_CCL")
        self.assertEqual(normalize_fx_pair(" usd-ars  official "), "USD_ARS_OFFICIAL")
        self.assertEqual(normalize_fx_pair("USDARS_MEP"), "USDARS_MEP")

    def test_empty_raises(self) -> None:
        with self.assertRaises(ValueError):
            normalize_fx_pair("   ")


class LoadSnapshotTests(unittest.TestCase):
    def test_loads_example_snapshot(self) -> None:
        snapshot = load_manual_market_snapshot(EXAMPLE_PATH)
        self.assertTrue(snapshot.manual_review_only)
        self.assertFalse(snapshot.live_trading_enabled)
        self.assertEqual(snapshot.snapshot_id, "manual-example-2026-05-12")
        self.assertIn("SPY", snapshot.quotes)
        self.assertIn("GGAL", snapshot.quotes)
        self.assertIn("USDARS_MEP", snapshot.fx_rates)
        self.assertIn("money_market_monthly_pct", snapshot.rates)
        self.assertEqual(snapshot.completeness, "partial")
        self.assertTrue(len(snapshot.warnings) >= 1)

    def test_summary_reports_counts(self) -> None:
        snapshot = load_manual_market_snapshot(EXAMPLE_PATH)
        summary = summarize_snapshot(snapshot)
        self.assertEqual(summary["snapshot_id"], snapshot.snapshot_id)
        self.assertEqual(summary["quotes_loaded"], len(snapshot.quotes))
        self.assertEqual(summary["fx_rates_loaded"], len(snapshot.fx_rates))
        self.assertEqual(summary["rates_loaded"], len(snapshot.rates))
        self.assertEqual(summary["completeness"], "partial")

    def test_symbol_normalized_on_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = _example_payload()
            payload["quotes"] = [
                {
                    "symbol": " ggal.ba ",
                    "asset_class": "argentina_equity",
                    "price": 5000.0,
                    "currency": "ARS",
                    "as_of": "2026-05-12",
                }
            ]
            path = _write_tmp(payload, tmp_path)
            snapshot = load_manual_market_snapshot(path)
            self.assertIn("GGAL", snapshot.quotes)

    def test_snapshot_to_static_provider(self) -> None:
        snapshot = load_manual_market_snapshot(EXAMPLE_PATH)
        provider = snapshot_to_static_provider(snapshot)
        self.assertIsInstance(provider, StaticArgentinaMarketDataProvider)
        health = provider.health_check()
        self.assertTrue(health["ok"])
        self.assertFalse(health["network_required"])
        self.assertFalse(health["live_trading_enabled"])
        self.assertGreaterEqual(health["quotes_loaded"], 2)
        # Quote round-trip
        quote = provider.get_latest_quote("SPY")
        self.assertEqual(quote.last_price, 10000.0)
        self.assertEqual(quote.source, "manual_snapshot")
        self.assertTrue(quote.is_delayed)

    def test_get_fx_rate_normalizes_input(self) -> None:
        snapshot = load_manual_market_snapshot(EXAMPLE_PATH)
        rate = get_fx_rate(snapshot, "usdars mep")
        self.assertIsNotNone(rate)
        self.assertEqual(rate.pair, "USDARS_MEP")
        self.assertEqual(rate.rate, 1200.0)
        self.assertIsNone(get_fx_rate(snapshot, "EURUSD"))

    def test_get_rate_input_case_insensitive_and_missing(self) -> None:
        snapshot = load_manual_market_snapshot(EXAMPLE_PATH)
        entry = get_rate_input(snapshot, "MONEY_MARKET_MONTHLY_PCT")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.value, 2.5)
        self.assertIsNone(get_rate_input(snapshot, "nope"))


class InvalidSnapshotTests(unittest.TestCase):
    def test_missing_top_level_field_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = _example_payload()
            payload.pop("snapshot_id")
            path = _write_tmp(payload, tmp_path)
            with self.assertRaises(ValueError):
                load_manual_market_snapshot(path)

    def test_live_trading_true_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = _example_payload()
            payload["live_trading_enabled"] = True
            path = _write_tmp(payload, tmp_path)
            with self.assertRaises(ValueError):
                load_manual_market_snapshot(path)

    def test_manual_review_false_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = _example_payload()
            payload["manual_review_only"] = False
            path = _write_tmp(payload, tmp_path)
            with self.assertRaises(ValueError):
                load_manual_market_snapshot(path)

    def test_non_positive_quote_price_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = _example_payload()
            payload["quotes"] = copy.deepcopy(payload["quotes"])
            payload["quotes"][0]["price"] = 0
            path = _write_tmp(payload, tmp_path)
            with self.assertRaises(ValueError):
                load_manual_market_snapshot(path)

    def test_non_positive_fx_rate_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = _example_payload()
            payload["fx_rates"] = copy.deepcopy(payload["fx_rates"])
            payload["fx_rates"]["USDARS_MEP"]["rate"] = -1
            path = _write_tmp(payload, tmp_path)
            with self.assertRaises(ValueError):
                load_manual_market_snapshot(path)

    def test_quotes_not_list_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            payload = _example_payload()
            payload["quotes"] = {}
            path = _write_tmp(payload, tmp_path)
            with self.assertRaises(ValueError):
                load_manual_market_snapshot(path)

    def test_missing_file_raises(self) -> None:
        with self.assertRaises(ValueError):
            load_manual_market_snapshot(Path("/nonexistent/snapshot.json"))


if __name__ == "__main__":
    unittest.main()
