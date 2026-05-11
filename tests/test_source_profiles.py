import unittest

from src.asset_universe import iter_assets
from src.source_profiles import (
    filter_free_fundamentals_assets,
    filter_free_price_assets,
    get_profile_asset_ids,
)


class SourceProfilesTests(unittest.TestCase):
    def test_known_profile_returns_assets(self) -> None:
        asset_ids = get_profile_asset_ids("free-core")
        self.assertIn("AAPL.US", asset_ids)
        self.assertIn("EURUSD.FX", asset_ids)

    def test_free_price_filter_excludes_ba(self) -> None:
        assets = iter_assets(asset_ids=["AAPL.US", "GGAL.BA", "EURUSD.FX"])
        filtered = filter_free_price_assets(assets)
        filtered_ids = [asset.asset_id for asset in filtered]
        self.assertIn("AAPL.US", filtered_ids)
        self.assertIn("EURUSD.FX", filtered_ids)
        self.assertNotIn("GGAL.BA", filtered_ids)

    def test_free_fundamentals_filter_keeps_us_equities_only(self) -> None:
        assets = iter_assets(asset_ids=["AAPL.US", "SPY.US", "EURUSD.FX"])
        filtered = filter_free_fundamentals_assets(assets)
        filtered_ids = [asset.asset_id for asset in filtered]
        self.assertIn("AAPL.US", filtered_ids)
        self.assertNotIn("SPY.US", filtered_ids)
        self.assertNotIn("EURUSD.FX", filtered_ids)


if __name__ == "__main__":
    unittest.main()
