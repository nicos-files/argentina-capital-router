"""FX opportunity placeholder.

Manual review only. No external data calls in this slice.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FxOpportunityInputs:
    opportunity_id: str
    notes: str = ""


def score_fx_opportunity(inputs: FxOpportunityInputs):  # pragma: no cover - placeholder
    raise NotImplementedError("FX opportunity scoring not implemented in this slice.")


__all__ = ["FxOpportunityInputs", "score_fx_opportunity"]
