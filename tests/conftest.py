"""Shared fixtures/builders for risk-engine tests.

Baseline scenario: $100k equity, MGC at 2000.0 with daily ATR(14) = 20.0
points. MGC point value is $10, so a 2xATR stop (40 points) risks $400 per
contract and a 0.5% risk budget ($500) sizes exactly 1 contract.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from goldguard.core.models import MGC, Instrument, OrderIntent, OrderType, Position, Side, SystemState
from goldguard.risk.config import RiskConfig
from goldguard.risk.engine import RiskEngine
from goldguard.risk.state import AccountState, MarketState, PortfolioState

ET = ZoneInfo("America/New_York")

# A Tuesday, mid-session, far from any blackout window.
SAFE_NOW = datetime(2026, 6, 9, 11, 0, tzinfo=ET)

GC = Instrument(symbol="GC", exchange="COMEX", tick_size=0.1, tick_value=10.0, multiplier=100, margin_estimate=11500.0)
ZC = Instrument(symbol="ZC", exchange="CBOT", tick_size=0.25, tick_value=12.5, multiplier=5000, margin_estimate=2100.0)


def make_account(
    equity: float = 100_000.0,
    margin_capacity: float = 100_000.0,
    margin_used: float = 0.0,
    state: SystemState = SystemState.RUNNING,
    size_multiplier: float = 1.0,
) -> AccountState:
    return AccountState(
        equity=equity,
        margin_capacity=margin_capacity,
        margin_used=margin_used,
        system_state=state,
        size_multiplier=size_multiplier,
    )


def make_market(now: datetime = SAFE_NOW, atr: float = 20.0, **kw) -> MarketState:
    return MarketState(now=now, atr_14=atr, **kw)


def make_intent(
    side: Side = Side.BUY,
    qty: int = 1,
    entry: float = 2000.0,
    stop_atr_multiple: float = 2.0,
    atr: float = 20.0,
    instrument: Instrument = MGC,
    **kw,
) -> OrderIntent:
    distance = stop_atr_multiple * atr
    stop = entry - distance if side is Side.BUY else entry + distance
    return OrderIntent(
        instrument=instrument,
        side=side,
        qty=qty,
        type=OrderType.LIMIT,
        limit_price=entry,
        stop_price=stop,
        **kw,
    )


def make_position(
    instrument: Instrument = MGC, qty: int = 1, avg_price: float = 2000.0, stop_price: float = 1960.0
) -> Position:
    return Position(
        instrument=instrument, qty=qty, avg_price=avg_price, stop_price=stop_price, broker_stop_order_id="stop-1"
    )


def make_engine(**config_overrides) -> RiskEngine:
    return RiskEngine(RiskConfig(**config_overrides))


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


EMPTY_PORTFOLIO = PortfolioState()
