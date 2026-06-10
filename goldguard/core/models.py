"""Core domain models (spec §2). All Pydantic v2, all immutable by default.

These models are shared by the risk engine, signals, execution, and the
backtester so that every layer speaks the same types and the backtester can
replay the exact live code path.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Instrument(Frozen):
    symbol: str
    exchange: str
    tick_size: float = Field(gt=0)
    tick_value: float = Field(gt=0)
    multiplier: int = Field(gt=0)
    margin_estimate: float = Field(gt=0)

    @property
    def point_value(self) -> float:
        """Dollar value of a 1.0 price move for one contract."""
        return self.tick_value / self.tick_size


MGC = Instrument(
    symbol="MGC", exchange="COMEX", tick_size=0.1, tick_value=1.0, multiplier=10, margin_estimate=1150.0
)


class Timeframe(StrEnum):
    DAILY = "1d"
    HOURLY = "1h"


class Bar(Frozen):
    timestamp: datetime
    timeframe: Timeframe
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class Direction(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


class Signal(Frozen):
    direction: Direction
    strength: float = Field(ge=0.0, le=1.0)
    strategy_id: str
    timestamp: datetime
    proposed_stop_atr_multiple: float = Field(gt=0)


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"


class OrderIntent(Frozen):
    instrument: Instrument
    side: Side
    qty: int = Field(gt=0)
    type: OrderType = OrderType.LIMIT
    limit_price: float | None = None
    stop_price: float | None = None  # broker-side protective stop; mandatory for entries
    client_order_id: UUID = Field(default_factory=uuid4)
    parent_signal_id: str | None = None
    reduces_position: bool = False  # exits/flattens; exempt from entry-only checks

    @property
    def entry_price(self) -> float:
        """Reference price for risk distance: limit price (limit-or-better, spec §4)."""
        if self.limit_price is None:
            raise ValueError("OrderIntent requires a limit_price reference for risk evaluation")
        return self.limit_price


class Verdict(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    MODIFIED = "MODIFIED"


class RiskVerdict(Frozen):
    verdict: Verdict
    reasons: list[str] = []
    final_qty: int = 0

    @property
    def allowed(self) -> bool:
        return self.verdict in (Verdict.APPROVED, Verdict.MODIFIED)


class Position(Frozen):
    instrument: Instrument
    qty: int  # signed: + long, - short
    avg_price: float
    stop_price: float
    unrealized_pnl: float = 0.0
    broker_stop_order_id: str | None = None

    @property
    def open_risk(self) -> float:
        """Dollars lost if the stop is hit from avg_price."""
        return abs(self.avg_price - self.stop_price) * abs(self.qty) * self.instrument.point_value


class SystemState(StrEnum):
    RUNNING = "RUNNING"
    SOFT_HALT = "SOFT_HALT"
    HARD_HALT = "HARD_HALT"
    FLATTENING = "FLATTENING"
    FLAT_LOCKED = "FLAT_LOCKED"


class AuditEvent(Frozen):
    timestamp: datetime
    kind: str  # state_transition | signal | risk_verdict | order | fill | reconciliation | config
    payload: dict[str, Any]
