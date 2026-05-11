import json
import unittest
from pathlib import Path

from src.decision_intel.contracts.metadata_models import CURRENT_SCHEMA_VERSION, MIN_READER_VERSION
from src.decision_intel.contracts.recommendations.recommendation_models import (
    RecommendationItem,
    RecommendationOutput,
)


class RecommendationContractTests(unittest.TestCase):
    def test_schema_version_constant_matches_repo_version(self) -> None:
        schema_path = (
            Path(__file__).resolve().parents[3]
            / "src"
            / "decision_intel"
            / "contracts"
            / "recommendations"
            / "recommendation_output.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["schema_version"]["const"], CURRENT_SCHEMA_VERSION)
        self.assertEqual(schema["properties"]["reader_min_version"]["const"], MIN_READER_VERSION)

    def test_recommendation_item_roundtrip_preserves_extensions(self) -> None:
        raw = {
            "ticker": "AAPL.US",
            "asset_id": "AAPL.US",
            "horizon": "INTRADAY",
            "action": "BUY",
            "weight": 0.2,
            "usd_target": 20.0,
            "usd_target_effective": 20.0,
            "broker_selected": "generic_us",
            "current_qty": 0.0,
            "qty_target": 0.2,
            "delta_qty": 0.2,
            "order_side": "BUY",
            "order_type": "MARKET",
            "time_in_force": "DAY",
            "order_qty": 0.2,
            "order_notional_usd": 20.0,
            "order_notional_ccy": 20.0,
            "min_notional_usd": 1.0,
            "order_status": "READY",
            "cash_available_usd": 100.0,
            "cash_used_usd": 20.0,
            "price_used": 100.0,
            "price_source": "features.close",
            "currency": "USD",
            "fx_rate_used": 1.0,
            "fx_rate_source": "native_usd",
            "lot_size": 1,
            "allow_fractional": True,
            "expected_return_gross_pct": 0.02,
            "expected_return_net_pct": 0.01,
            "expected_return_net_usd": 0.2,
            "expected_return_source": "calibrated",
            "fees_estimated_usd": 1.0,
            "fees_one_way": 0.5,
            "fees_round_trip": 1.0,
            "broker_costs": {"generic_us": {"fee_one_way": 0.5}},
            "reason": "test",
            "policy_id": "policy.test",
            "policy_version": "1",
            "constraints": [],
            "sizing_rule": "weights.normalized_pct",
            "strategy_id": "intraday.crypto.v1",
        }
        item = RecommendationItem.from_dict(raw)
        payload = item.to_dict()
        self.assertEqual(payload["asset_id"], "AAPL.US")
        self.assertEqual(payload["strategy_id"], "intraday.crypto.v1")

    def test_recommendation_output_builds_payload(self) -> None:
        output = RecommendationOutput.build(
            run_id="20260424-1800",
            horizon="INTRADAY",
            asof_date="2026-04-23",
            policy_id="policy.test",
            policy_version="1",
            constraints=[],
            sizing_rule="weights.normalized_pct",
            recommendations=[
                {
                    "ticker": "BTCUSD.CRYPTO",
                    "asset_id": "BTCUSD.CRYPTO",
                    "horizon": "INTRADAY",
                    "action": "SKIP",
                    "weight": 0.0,
                    "usd_target": 0.0,
                    "usd_target_effective": 0.0,
                    "broker_selected": "paper",
                    "current_qty": 0.0,
                    "qty_target": 0.0,
                    "delta_qty": 0.0,
                    "order_side": None,
                    "order_type": "MARKET",
                    "time_in_force": "DAY",
                    "order_qty": 0.0,
                    "order_notional_usd": 0.0,
                    "order_notional_ccy": 0.0,
                    "min_notional_usd": 0.0,
                    "order_status": "NO_ORDER",
                    "cash_available_usd": None,
                    "cash_used_usd": 0.0,
                    "price_used": 0.0,
                    "price_source": "features.close",
                    "currency": "USD",
                    "fx_rate_used": 1.0,
                    "fx_rate_source": "native_usd",
                    "lot_size": 1,
                    "allow_fractional": True,
                    "expected_return_gross_pct": 0.0,
                    "expected_return_net_pct": 0.0,
                    "expected_return_net_usd": 0.0,
                    "expected_return_source": "calibrated",
                    "fees_estimated_usd": 0.0,
                    "fees_one_way": 0.0,
                    "fees_round_trip": 0.0,
                    "broker_costs": {},
                    "reason": "none",
                    "policy_id": "policy.test",
                    "policy_version": "1",
                    "constraints": [],
                    "sizing_rule": "weights.normalized_pct",
                }
            ],
            cash_summary={"INTRADAY": {"capital_usd": 100.0}},
            cash_policy="clip_to_available",
        )
        payload = output.to_payload()
        self.assertEqual(payload["schema_version"], CURRENT_SCHEMA_VERSION)
        self.assertEqual(payload["recommendations"][0]["asset_id"], "BTCUSD.CRYPTO")


if __name__ == "__main__":
    unittest.main()
