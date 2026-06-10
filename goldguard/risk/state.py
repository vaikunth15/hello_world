"""Input state snapshots for the risk engine. Pure data — the engine never
performs I/O; callers assemble these from broker/DB/clock and pass them in,
which is what makes ``evaluate`` deterministic and replayable."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from goldguard.core.models import Frozen, Position, SystemState


class AccountState(Frozen):
    equity: float = Field(gt=0)
    margin_capacity: float = Field(ge=0)  # broker-reported available margin basis
    margin_used: float = Field(ge=0)
    system_state: SystemState = SystemState.RUNNING
    size_multiplier: float = Field(default=1.0, gt=0, le=1.0)  # from drawdown ladder


class PortfolioState(Frozen):
    positions: list[Position] = []

    def position_in(self, symbol: str) -> Position | None:
        for p in self.positions:
            if p.instrument.symbol == symbol and p.qty != 0:
                return p
        return None

    @property
    def total_open_risk(self) -> float:
        return sum(p.open_risk for p in self.positions)


class EconomicEvent(Frozen):
    name: str
    timestamp: datetime
    impact: str = "high"


class MarketState(Frozen):
    now: datetime  # tz-aware, the only clock the engine sees
    atr_14: float = Field(gt=0)  # daily ATR(14) in price points
    session_open: datetime | None = None
    upcoming_events: list[EconomicEvent] = []
