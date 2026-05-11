from __future__ import annotations

from typing import Any, Dict


def sizing_fixed(context: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    return {"position_size": config.get("size", 1.0)}


def constraint_max_positions(context: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    return {"max_positions": config.get("max_positions", 10)}


def filter_min_liquidity(context: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:
    return {"min_liquidity": config.get("min_liquidity", 0)}
