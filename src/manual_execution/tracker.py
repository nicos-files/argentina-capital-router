"""Minimal manual-execution tracker.

This module records, in memory, that a recommendation was reviewed/executed by a
human. It never talks to brokers and never places orders.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class ManualExecutionEntry:
    as_of: str
    symbol: str
    action: str
    quantity_or_usd: float
    notes: str = ""
    reviewed_by: str = ""


@dataclass
class ManualExecutionTracker:
    entries: List[ManualExecutionEntry] = field(default_factory=list)

    def record(self, entry: ManualExecutionEntry) -> None:
        self.entries.append(entry)

    def to_list(self) -> list[dict]:
        return [
            {
                "as_of": e.as_of,
                "symbol": e.symbol,
                "action": e.action,
                "quantity_or_usd": e.quantity_or_usd,
                "notes": e.notes,
                "reviewed_by": e.reviewed_by,
            }
            for e in self.entries
        ]


__all__ = ["ManualExecutionEntry", "ManualExecutionTracker"]
