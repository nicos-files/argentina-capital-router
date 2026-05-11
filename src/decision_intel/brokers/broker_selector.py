from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Tuple


BROKERS: Dict[str, Dict[str, float]] = {
    "balanz": {"commission_pct": 0.006, "min_usd": 5.0},
    "iol": {"commission_pct": 0.005, "min_usd": 5.0},
    "generic_us": {"commission_pct": 0.002, "min_usd": 1.0},
}

BROKER_FRACTIONAL = {"balanz": False, "iol": False, "generic_us": True}
DEFAULT_BROKER = "generic_us"
BROKER_MIN_NOTIONAL_USD = {"balanz": 50.0, "iol": 50.0, "generic_us": 1.0}


@dataclass(frozen=True)
class BrokerSelection:
    broker: str
    fee_one_way: float
    fee_round_trip: float


def build_fee_table(usd_amount: float, brokers: Iterable[str] | None = None) -> Dict[str, Dict[str, float]]:
    table: Dict[str, Dict[str, float]] = {}
    broker_names = list(brokers) if brokers is not None else list(BROKERS.keys())
    for broker_name in broker_names:
        config = BROKERS.get(broker_name)
        if not config:
            continue
        commission_pct = float(config["commission_pct"])
        min_usd = float(config["min_usd"])
        fee = max(min_usd, commission_pct * usd_amount) if usd_amount > 0 else 0.0
        table[broker_name] = {
            "commission_pct": commission_pct,
            "min_usd": min_usd,
            "fee_one_way": fee,
            "fee_round_trip": 2.0 * fee,
        }
    return table


def select_broker(
    usd_amount: float,
    currency: str | None = None,
    asset_type: str | None = None,
    brokers: Iterable[str] | None = None,
) -> BrokerSelection:
    _ = (currency, asset_type)
    if usd_amount <= 0:
        return BrokerSelection(DEFAULT_BROKER, 0.0, 0.0)
    fee_table = build_fee_table(usd_amount, brokers=brokers)
    choices = []
    for broker_name, entry in fee_table.items():
        choices.append((float(entry["fee_one_way"]), broker_name))
    choices.sort(key=lambda item: (item[0], item[1]))
    best_fee, best_broker = choices[0]
    return BrokerSelection(best_broker, best_fee, 2.0 * best_fee)


def broker_min_notional_usd(broker: str, currency: str | None = None) -> float:
    _ = currency
    return float(BROKER_MIN_NOTIONAL_USD.get(broker, 0.0))
