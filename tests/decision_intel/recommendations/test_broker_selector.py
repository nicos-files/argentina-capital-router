import unittest

from src.decision_intel.brokers.broker_selector import select_broker


class BrokerSelectorTests(unittest.TestCase):
    def test_select_broker_lowest_fee(self) -> None:
        selection = select_broker(100.0)
        self.assertEqual(selection.broker, "generic_us")
        self.assertAlmostEqual(selection.fee_one_way, 1.0, places=6)

    def test_select_broker_zero_amount(self) -> None:
        selection = select_broker(0.0)
        self.assertEqual(selection.fee_one_way, 0.0)
        self.assertEqual(selection.fee_round_trip, 0.0)


if __name__ == "__main__":
    unittest.main()
