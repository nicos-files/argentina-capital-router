import unittest

from src.capital_allocation.buckets import build_default_capital_state


class BucketsTests(unittest.TestCase):
    def test_build_default_capital_state(self) -> None:
        state = build_default_capital_state(monthly_contribution_usd=200, tactical_capital_available_usd=50)
        self.assertEqual(state.monthly_long_term_contribution_usd, 200)
        self.assertEqual(state.long_term_bucket.available_usd, 200)
        self.assertTrue(state.long_term_bucket.is_mandatory_long_term)
        self.assertEqual(state.tactical_bucket.available_usd, 50)
        self.assertFalse(state.tactical_bucket.is_mandatory_long_term)
        self.assertEqual(state.total_capital_usd, 250)

    def test_negative_raises(self) -> None:
        with self.assertRaises(ValueError):
            build_default_capital_state(monthly_contribution_usd=-1)
        with self.assertRaises(ValueError):
            build_default_capital_state(tactical_capital_available_usd=-1)


if __name__ == "__main__":
    unittest.main()
