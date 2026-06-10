"""Reconciler (spec §5): every 60s, compare broker truth against the local
book. One re-sync attempt on mismatch; if it persists, flatten everything,
HARD_HALT, and alert. Position truth lives at the broker."""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from goldguard.core.models import Position
from goldguard.core.logging import get_logger
from goldguard.execution.broker import BrokerAdapter
from goldguard.execution.order_manager import HaltFn

log = get_logger("reconciler")

AlertFn = Callable[[str], None]


def _book(positions: list[Position]) -> dict[str, int]:
    return {p.instrument.symbol: p.qty for p in positions if p.qty != 0}


class Reconciler:
    def __init__(self, broker: BrokerAdapter, local_positions: Callable[[], list[Position]],
                 halt: HaltFn, alert: AlertFn):
        self._broker = broker
        self._local = local_positions
        self._halt = halt
        self._alert = alert

    def run_once(self, now: datetime) -> bool:
        """Returns True when books match (possibly after one re-sync)."""
        broker_book = _book(self._broker.positions())
        local_book = _book(self._local())
        if broker_book == local_book:
            return True

        log.critical("position mismatch", broker=broker_book, local=local_book)
        # One re-sync attempt: re-read both sides in case we raced a fill.
        broker_book = _book(self._broker.positions())
        local_book = _book(self._local())
        if broker_book == local_book:
            log.warning("mismatch resolved on re-sync")
            return True

        self._alert(f"RECONCILER MISMATCH broker={broker_book} local={local_book} — flattening")
        self._broker.flatten_all()
        self._halt("unresolved position mismatch — flattened", True)
        return False
