"""Capital buckets for manual-review-only capital routing."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CapitalBucket:
    bucket_id: str
    description: str
    available_usd: float
    is_mandatory_long_term: bool = False


@dataclass(frozen=True)
class CapitalState:
    monthly_long_term_contribution_usd: float
    long_term_bucket: CapitalBucket
    tactical_bucket: CapitalBucket
    metadata: dict = field(default_factory=dict)

    @property
    def total_capital_usd(self) -> float:
        return float(self.long_term_bucket.available_usd) + float(
            self.tactical_bucket.available_usd
        )


def build_default_capital_state(
    monthly_contribution_usd: float = 200.0,
    tactical_capital_available_usd: float = 0.0,
) -> CapitalState:
    contribution = float(monthly_contribution_usd)
    tactical = float(tactical_capital_available_usd)
    if contribution < 0:
        raise ValueError("monthly_contribution_usd must be >= 0")
    if tactical < 0:
        raise ValueError("tactical_capital_available_usd must be >= 0")

    long_term = CapitalBucket(
        bucket_id="long_term_contribution",
        description="Mandatory monthly long-term contribution (must be invested by end of month).",
        available_usd=contribution,
        is_mandatory_long_term=True,
    )
    tactical_bucket = CapitalBucket(
        bucket_id="tactical_bucket",
        description="Optional tactical capital. Loss absorption first.",
        available_usd=tactical,
        is_mandatory_long_term=False,
    )
    return CapitalState(
        monthly_long_term_contribution_usd=contribution,
        long_term_bucket=long_term,
        tactical_bucket=tactical_bucket,
    )


__all__ = ["CapitalBucket", "CapitalState", "build_default_capital_state"]
