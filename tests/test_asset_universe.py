import unittest

from src.asset_universe import get_asset_definition, iter_assets, load_asset_universe


class AssetUniverseTests(unittest.TestCase):
    def test_universe_catalog_loads(self) -> None:
        assets = load_asset_universe()
        self.assertGreaterEqual(len(assets), 20)

    def test_can_lookup_cedear_and_forex_assets(self) -> None:
        cedear = get_asset_definition("AAPL.BA")
        forex = get_asset_definition("EURUSD.FX")
        self.assertIsNotNone(cedear)
        self.assertIsNotNone(forex)
        self.assertEqual(cedear.market, "BA")
        self.assertEqual(forex.asset_class, "FOREX")
        self.assertEqual(forex.yfinance_symbol, "EURUSD=X")

    def test_filters_by_market_and_asset_class(self) -> None:
        fx_assets = iter_assets(asset_classes=["FOREX"])
        ba_assets = iter_assets(markets=["BA"])
        self.assertTrue(all(asset.asset_class == "FOREX" for asset in fx_assets))
        self.assertTrue(all(asset.market == "BA" for asset in ba_assets))


if __name__ == "__main__":
    unittest.main()
