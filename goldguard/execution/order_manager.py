"""OrderManager (spec §5). Final gate between verdicts and the broker.

Hard rules, none configurable:
- Nothing is sent without an allowed RiskVerdict; the order quantity is the
  verdict's final_qty, never the intent's.
- Entries without a stop are rejected here too (double enforcement of §3.1).
- Idempotency: a client_order_id that was ever sent is never re-sent.
- Rate limiter: > 5 orders/minute or > 20 orders/day triggers HARD_HALT and
  the order is NOT sent. The Knight Capital defense — the constants below
  are intentionally not constructor parameters.
- If the entry fills but the protective stop fails, the entry is flattened
  immediately and the system SOFT_HALTs.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from typing import Callable, Protocol
from uuid import UUID

from goldguard.core.models import OrderIntent, RiskVerdict
from goldguard.execution.broker import BracketIds, BrokerAdapter, BrokerError

MAX_ORDERS_PER_MINUTE = 5
MAX_ORDERS_PER_DAY = 20

HaltFn = Callable[[str, bool], None]  # (reason, hard)


class OrderStore(Protocol):
    def was_sent(self, client_order_id: UUID) -> bool: ...
    def mark_sent(self, client_order_id: UUID, when: datetime) -> None: ...


class MemoryOrderStore:
    def __init__(self) -> None:
        self._sent: dict[UUID, datetime] = {}

    def was_sent(self, client_order_id: UUID) -> bool:
        return client_order_id in self._sent

    def mark_sent(self, client_order_id: UUID, when: datetime) -> None:
        self._sent[client_order_id] = when


class RateLimiter:
    def __init__(self) -> None:
        self._minute: deque[datetime] = deque()
        self._day: deque[datetime] = deque()

    def try_acquire(self, now: datetime) -> bool:
        while self._minute and now - self._minute[0] >= timedelta(minutes=1):
            self._minute.popleft()
        while self._day and now - self._day[0] >= timedelta(days=1):
            self._day.popleft()
        if len(self._minute) >= MAX_ORDERS_PER_MINUTE or len(self._day) >= MAX_ORDERS_PER_DAY:
            return False
        self._minute.append(now)
        self._day.append(now)
        return True


class OrderResult:
    def __init__(self, sent: bool, reason: str = "", bracket: BracketIds | None = None):
        self.sent = sent
        self.reason = reason
        self.bracket = bracket


class OrderManager:
    def __init__(self, broker: BrokerAdapter, store: OrderStore, halt: HaltFn):
        self._broker = broker
        self._store = store
        self._halt = halt
        self._limiter = RateLimiter()

    def execute(self, intent: OrderIntent, verdict: RiskVerdict, now: datetime) -> OrderResult:
        if not verdict.allowed:
            return OrderResult(False, f"risk verdict {verdict.verdict}: {verdict.reasons}")
        if intent.stop_price is None:
            return OrderResult(False, "entry without stop rejected at OrderManager (double enforcement)")
        if self._store.was_sent(intent.client_order_id):
            return OrderResult(False, f"duplicate client_order_id {intent.client_order_id}, not re-sent")
        if not self._limiter.try_acquire(now):
            self._halt("order rate limit exceeded (Knight defense)", True)
            return OrderResult(False, "rate limit exceeded -> HARD_HALT")

        sized = intent.model_copy(update={"qty": verdict.final_qty})
        self._store.mark_sent(sized.client_order_id, now)
        try:
            bracket = self._broker.place_bracket(sized)
        except BrokerError as exc:
            # Either the entry never happened (safe) or it filled without a
            # stop (unsafe). Flatten unconditionally — a stopless position
            # must not survive — then stand down for the day.
            self._broker.flatten_all()
            self._halt(f"bracket placement failed: {exc}", False)
            return OrderResult(False, f"bracket failed, flattened + SOFT_HALT: {exc}")
        return OrderResult(True, bracket=bracket)
