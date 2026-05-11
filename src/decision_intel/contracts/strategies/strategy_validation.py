from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from src.decision_intel.contracts.strategies.strategy_constants import SCHEMA_VERSION
from src.decision_intel.contracts.strategies.strategy_loader import StrategyConfigError


def validate_strategy_config(path: str | Path) -> Dict[str, Any]:
    config_path = Path(path)
    data = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise StrategyConfigError("INVALID_CONFIG", "strategy config must be a JSON object")
    if data.get("schema_version") != SCHEMA_VERSION:
        raise StrategyConfigError("SCHEMA_VERSION_MISMATCH", "unsupported schema_version")
    # reuse loader validation path for full checks
    from src.decision_intel.contracts.strategies.strategy_loader import _validate_schema

    _validate_schema(data)
    return data
