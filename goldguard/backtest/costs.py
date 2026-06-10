"""Mandatory trading costs (spec §7): commission per side plus a slippage
model — 1 tick on normal days, 4 ticks on scheduled high-impact event days."""

from __future__ import annotations

from datetime import date

from pydantic import Field

from goldguard.core.models import Frozen, Instrument


class CostModel(Frozen):
    commission_per_side: float = Field(default=1.24, ge=0)
    slip_ticks_normal: int = Field(default=1, ge=0)
    slip_ticks_event: int = Field(default=4, ge=0)
    event_days: frozenset[date] = frozenset()

    def slippage_points(self, instrument: Instrument, day: date) -> float:
        ticks = self.slip_ticks_event if day in self.event_days else self.slip_ticks_normal
        return ticks * instrument.tick_size

    def commission(self, qty: int) -> float:
        return self.commission_per_side * qty
