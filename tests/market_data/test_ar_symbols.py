import json
import unittest
from pathlib import Path

from src.market_data.ar_symbols import (
    get_asset_by_symbol,
    get_enabled_long_term_assets,
    get_provider_symbol,
    load_ar_long_term_universe,
    normalize_ar_symbol,
)


class NormalizeArSymbolTests(unittest.TestCase):
    def test_examples(self) -> None:
        self.assertEqual(normalize_ar_symbol(" ggal "), "GGAL")
        self.assertEqual(normalize_ar_symbol("GGAL.BA"), "GGAL")
        self.assertEqual(normalize_ar_symbol("meli cedear"), "MELI")
        self.assertEqual(normalize_ar_symbol("AAPL CEDEAR"), "AAPL")

    def test_empty_raises(self) -> None:
        with self.assertRaises(ValueError):
            normalize_ar_symbol("   ")


class LoadUniverseTests(unittest.TestCase):
    def test_load_default(self) -> None:
        assets = load_ar_long_term_universe()
        self.assertGreaterEqual(len(assets), 10)
        symbols = {a.symbol for a in assets}
        for expected in ("GGAL", "MELI", "SPY"):
            self.assertIn(expected, symbols)

    def test_enabled_long_term_assets(self) -> None:
        assets = get_enabled_long_term_assets()
        self.assertTrue(all(a.enabled and a.long_term_enabled for a in assets))

    def test_get_asset_by_symbol(self) -> None:
        asset = get_asset_by_symbol("ggal")
        self.assertIsNotNone(asset)
        self.assertEqual(asset.symbol, "GGAL")
        self.assertIsNone(get_asset_by_symbol("ZZZZ"))

    def test_get_provider_symbol_case_insensitive(self) -> None:
        asset = get_asset_by_symbol("GGAL")
        self.assertIsNotNone(asset)
        # case-insensitive lookup; uses exact mapping when present
        self.assertEqual(get_provider_symbol(asset, "YFINANCE"), "GGAL.BA")
        # missing provider falls back to internal
        self.assertEqual(get_provider_symbol(asset, "doesnotexist"), "GGAL")

    def test_get_provider_symbol_returns_none_when_no_mapping(self) -> None:
        asset = get_asset_by_symbol("GGAL")
        # Inject an asset whose source_symbol_map has no internal nor provider
        from src.market_data.ar_symbols import ArgentinaAsset

        empty = ArgentinaAsset(
            symbol="X",
            display_name="X",
            asset_class="argentina_equity",
            currency="ARS",
            market="BYMA",
            enabled=True,
            strategy_enabled=False,
            long_term_enabled=True,
            sector="x",
            risk_bucket="medium",
            min_notional=0.0,
            notes="",
            source_symbol_map={},
        )
        self.assertIsNone(get_provider_symbol(empty, "yfinance"))


class InvalidConfigTests(unittest.TestCase):
    def _write(self, tmp_path: Path, payload: dict) -> Path:
        path = tmp_path / "bad_universe.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_missing_top_level_field_raises(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bad = self._write(tmp_path, {"universe_id": "ar"})
            with self.assertRaises(ValueError):
                load_ar_long_term_universe(bad)

    def test_duplicate_symbols_raises(self) -> None:
        import tempfile

        asset = {
            "symbol": "GGAL",
            "display_name": "Galicia",
            "asset_class": "argentina_equity",
            "currency": "ARS",
            "market": "BYMA",
            "enabled": True,
            "strategy_enabled": False,
            "long_term_enabled": True,
            "sector": "fin",
            "risk_bucket": "medium",
            "min_notional": 0,
            "notes": "",
            "source_symbol_map": {"internal": "GGAL"},
        }
        payload = {
            "schema_version": "1.0",
            "universe_id": "ar_long_term",
            "base_currency": "ARS",
            "data_frequency": "1d",
            "execution_mode": "manual_review_only",
            "live_trading_enabled": False,
            "paper_trading_enabled": False,
            "assets": [asset, dict(asset)],
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            bad = self._write(tmp_path, payload)
            with self.assertRaises(ValueError):
                load_ar_long_term_universe(bad)


if __name__ == "__main__":
    unittest.main()
