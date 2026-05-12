"""Short-term rate opportunity placeholder.

Manual review only. No external data calls in this slice.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RateOpportunityInputs:
    opportunity_id: str
    notes: str = ""


def score_rate_opportunity(inputs: RateOpportunityInputs):  # pragma: no cover - placeholder
    raise NotImplementedError("Rate opportunity scoring not implemented in this slice.")


__all__ = ["RateOpportunityInputs", "score_rate_opportunity"]
