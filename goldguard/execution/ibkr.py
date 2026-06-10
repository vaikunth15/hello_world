"""Interactive Brokers adapter via ib_insync (paper account first, spec §9
Phase 4). Implements the same BrokerAdapter protocol as FakeBroker.

ib_insync is an optional dependency (``pip install goldguard[live]``); this
module imports lazily so the rest of the system tests without it. The bracket
uses IBKR native parent/child orders with ``transmit`` chaining so the
protective stop is part of the same atomic submission, and stops REST AT THE
BROKER (spec §0.4) — they survive an app crash.
"""

from __future__ import annotations

from goldguard.core.models import Instrument, OrderIntent, Position, Side
from goldguard.execution.broker import AccountSnapshot, BracketIds, BrokerError


class IBKRAdapter:
    def __init__(self, host: str = "127.0.0.1", port: int = 7497, client_id: int = 1):
        try:
            from ib_insync import IB  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover
            raise BrokerError("ib_insync not installed — pip install 'goldguard[live]'") from exc
        self._ib = IB()
        self._ib.connect(host, port, clientId=client_id)

    def _contract(self, instrument: Instrument):
        from ib_insync import ContFuture  # noqa: PLC0415

        return ContFuture(instrument.symbol, exchange=instrument.exchange, currency="USD")

    def place_bracket(self, intent: OrderIntent) -> BracketIds:
        from ib_insync import LimitOrder, StopOrder  # noqa: PLC0415

        if intent.stop_price is None or intent.limit_price is None:
            raise BrokerError("bracket requires limit and stop prices")
        contract = self._contract(intent.instrument)
        action = "BUY" if intent.side is Side.BUY else "SELL"
        reverse = "SELL" if intent.side is Side.BUY else "BUY"

        entry = LimitOrder(action, intent.qty, intent.limit_price, transmit=False,
                           orderRef=str(intent.client_order_id))
        entry_trade = self._ib.placeOrder(contract, entry)
        stop = StopOrder(reverse, intent.qty, intent.stop_price, transmit=True,
                         parentId=entry.orderId, orderRef=f"{intent.client_order_id}-stop")
        stop_trade = self._ib.placeOrder(contract, stop)

        self._ib.sleep(1.0)
        if stop_trade.orderStatus.status in ("Inactive", "Cancelled", "ApiCancelled"):
            raise BrokerError(f"stop placement failed: {stop_trade.orderStatus.status}")
        fill = entry_trade.orderStatus.avgFillPrice or intent.limit_price
        return BracketIds(
            entry_order_id=str(entry.orderId), stop_order_id=str(stop.orderId), fill_price=fill
        )

    def cancel(self, order_id: str) -> None:
        for trade in self._ib.openTrades():
            if str(trade.order.orderId) == order_id:
                self._ib.cancelOrder(trade.order)
                return
        raise BrokerError(f"unknown order {order_id}")

    def positions(self) -> list[Position]:
        out: list[Position] = []
        for p in self._ib.positions():
            stop = self._find_stop(p.contract.symbol)
            out.append(
                Position(
                    instrument=Instrument(
                        symbol=p.contract.symbol, exchange=p.contract.exchange or "COMEX",
                        tick_size=0.1, tick_value=1.0, multiplier=int(p.contract.multiplier or 10),
                        margin_estimate=1150.0,
                    ),
                    qty=int(p.position), avg_price=p.avgCost / max(1, int(p.contract.multiplier or 10)),
                    stop_price=stop[0] if stop else p.avgCost,
                    broker_stop_order_id=stop[1] if stop else None,
                )
            )
        return out

    def _find_stop(self, symbol: str) -> tuple[float, str] | None:
        for trade in self._ib.openTrades():
            if trade.contract.symbol == symbol and trade.order.orderType == "STP":
                return trade.order.auxPrice, str(trade.order.orderId)
        return None

    def account(self) -> AccountSnapshot:
        values = {v.tag: float(v.value) for v in self._ib.accountSummary()
                  if v.tag in ("NetLiquidation", "FullMaintMarginReq", "AvailableFunds")}
        return AccountSnapshot(
            equity=values.get("NetLiquidation", 0.0),
            margin_used=values.get("FullMaintMarginReq", 0.0),
            margin_capacity=values.get("NetLiquidation", 0.0),
        )

    def flatten_all(self) -> None:
        from ib_insync import MarketOrder  # noqa: PLC0415

        self._ib.reqGlobalCancel()
        for p in self._ib.positions():
            if p.position == 0:
                continue
            action = "SELL" if p.position > 0 else "BUY"
            self._ib.placeOrder(p.contract, MarketOrder(action, abs(int(p.position))))
