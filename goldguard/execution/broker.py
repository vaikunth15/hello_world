"""Broker adapter interface (spec §5) and the FakeBroker used by tests,
drills, and paper simulations.

The FakeBroker is deliberately stateful and failure-injectable: drills kill
the app while it holds positions, break stop placement, and desync positions
to prove the safety layers react.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Protocol

from goldguard.core.models import Frozen, Instrument, OrderIntent, Position, Side


class BrokerError(RuntimeError):
    pass


class AccountSnapshot(Frozen):
    equity: float
    margin_used: float
    margin_capacity: float


class BracketIds(Frozen):
    entry_order_id: str
    stop_order_id: str
    fill_price: float


class BrokerAdapter(Protocol):
    def place_bracket(self, intent: OrderIntent) -> BracketIds: ...
    def cancel(self, order_id: str) -> None: ...
    def positions(self) -> list[Position]: ...
    def account(self) -> AccountSnapshot: ...
    def flatten_all(self) -> None: ...


@dataclass
class _StopOrder:
    order_id: str
    symbol: str
    stop_price: float
    qty: int
    closes_long: bool
    active: bool = True


@dataclass
class FakeBroker:
    """In-memory broker. Entries fill immediately at the limit price plus
    ``slippage_points`` in the adverse direction; stops rest server-side and
    trigger on ``tick()`` regardless of whether the app is alive."""

    equity: float = 100_000.0
    margin_capacity: float = 100_000.0
    slippage_points: float = 0.0
    fail_stop_placement: bool = False
    fail_entry_placement: bool = False

    _positions: dict[str, Position] = field(default_factory=dict)
    _stops: dict[str, _StopOrder] = field(default_factory=dict)
    _ids: itertools.count = field(default_factory=lambda: itertools.count(1))
    flatten_calls: int = 0

    def place_bracket(self, intent: OrderIntent) -> BracketIds:
        if intent.stop_price is None:
            raise BrokerError("bracket requires a stop")  # belt and braces
        if self.fail_entry_placement:
            raise BrokerError("injected entry failure")
        symbol = intent.instrument.symbol
        adverse = self.slippage_points if intent.side is Side.BUY else -self.slippage_points
        fill = (intent.limit_price or intent.stop_price) + adverse
        signed = intent.qty if intent.side is Side.BUY else -intent.qty
        existing = self._positions.get(symbol)
        new_qty = (existing.qty if existing else 0) + signed
        entry_id = f"E{next(self._ids)}"

        if self.fail_stop_placement:
            # Entry filled, protective stop did not stick — the dangerous case.
            self._set_position(intent.instrument, new_qty, fill, stop=None)
            raise BrokerError("injected stop placement failure")

        stop_id = f"S{next(self._ids)}"
        self._set_position(intent.instrument, new_qty, fill, stop=intent.stop_price, stop_id=stop_id)
        if new_qty != 0:
            self._stops[stop_id] = _StopOrder(
                order_id=stop_id, symbol=symbol, stop_price=intent.stop_price,
                qty=abs(new_qty), closes_long=new_qty > 0,
            )
        return BracketIds(entry_order_id=entry_id, stop_order_id=stop_id, fill_price=fill)

    def _set_position(
        self, instrument: Instrument, qty: int, price: float, stop: float | None, stop_id: str | None = None
    ) -> None:
        if qty == 0:
            self._positions.pop(instrument.symbol, None)
            return
        self._positions[instrument.symbol] = Position(
            instrument=instrument, qty=qty, avg_price=price,
            stop_price=stop if stop is not None else price,  # stopless flagged via broker_stop_order_id=None
            broker_stop_order_id=stop_id,
        )

    def cancel(self, order_id: str) -> None:
        stop = self._stops.pop(order_id, None)
        if stop is None:
            raise BrokerError(f"unknown order {order_id}")

    def positions(self) -> list[Position]:
        return list(self._positions.values())

    def account(self) -> AccountSnapshot:
        margin = sum(
            abs(p.qty) * p.instrument.margin_estimate for p in self._positions.values()
        )
        return AccountSnapshot(equity=self.equity, margin_used=margin, margin_capacity=self.margin_capacity)

    def flatten_all(self) -> None:
        self.flatten_calls += 1
        self._positions.clear()
        self._stops.clear()

    # -- simulation helpers (not part of BrokerAdapter) -----------------

    def tick(self, symbol: str, price: float) -> bool:
        """Move the market. Server-side stops fire with no app involvement.
        Returns True if a stop executed."""
        for stop in list(self._stops.values()):
            if stop.symbol != symbol or not stop.active:
                continue
            hit = price <= stop.stop_price if stop.closes_long else price >= stop.stop_price
            if hit:
                del self._stops[stop.order_id]
                self._positions.pop(symbol, None)
                return True
        return False

    def inject_position(self, position: Position) -> None:
        """Drill hook: desync the broker from the local book."""
        self._positions[position.instrument.symbol] = position
