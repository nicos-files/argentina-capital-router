import unittest

from src.decision_intel.assets.asset_metadata import get_asset_metadata


class AssetMetadataTests(unittest.TestCase):
    def test_asset_metadata_no_suffix_defaults_usd(self) -> None:
        meta = get_asset_metadata("TSLA")
        self.assertEqual(meta.asset_class, "EQUITY")
        self.assertEqual(meta.market, "US")
        self.assertEqual(meta.currency, "USD")
        self.assertTrue(meta.allow_fractional)
        self.assertEqual(meta.fx_rate_used, 1.0)
        self.assertEqual(meta.fx_rate_source, "native_usd")

    def test_asset_metadata_us_suffix(self) -> None:
        meta = get_asset_metadata("AAPL.US")
        self.assertEqual(meta.asset_class, "EQUITY")
        self.assertEqual(meta.market, "US")
        self.assertEqual(meta.currency, "USD")
        self.assertTrue(meta.allow_fractional)
        self.assertEqual(meta.fx_rate_used, 1.0)
        self.assertEqual(meta.fx_rate_source, "native_usd")

    def test_asset_metadata_non_us_suffix(self) -> None:
        meta = get_asset_metadata("GGAL.BA")
        self.assertEqual(meta.asset_class, "EQUITY")
        self.assertEqual(meta.market, "BA")
        self.assertEqual(meta.currency, "ARS")
        self.assertFalse(meta.allow_fractional)
        self.assertIsNone(meta.fx_rate_used)
        self.assertEqual(meta.fx_rate_source, "missing")

    def test_asset_metadata_forex_pair_from_catalog(self) -> None:
        meta = get_asset_metadata("EURUSD.FX")
        self.assertEqual(meta.asset_class, "FOREX")
        self.assertEqual(meta.market, "FX")
        self.assertEqual(meta.currency, "USD")
        self.assertTrue(meta.allow_fractional)
        self.assertEqual(meta.fx_rate_used, 1.0)
        self.assertEqual(meta.fx_rate_source, "native_usd")


if __name__ == "__main__":
    unittest.main()
