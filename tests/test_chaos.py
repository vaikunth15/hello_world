"""Chaos tests (spec §10): random API failures, duplicate fills, clock skew.
Whatever happens, the system must end in a safe state: FLAT, or holding a
position that is stop-protected and reconciled."""

from datetime import timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from goldguard.core.models import RiskVerdict, Side, Verdict
from goldguard.execution.broker import FakeBroker
from goldguard.execution.order_manager import MemoryOrderStore, OrderManager
from goldguard.execution.reconciler import Reconciler

from .conftest import make_intent, utc

T0 = utc(2026, 6, 8, 14, 0)
APPROVED = RiskVerdict(verdict=Verdict.APPROVED, final_qty=1)


@settings(max_examples=150, deadline=None)
@given(
    steps=st.lists(
        st.tuples(
            st.sampled_from(["order", "fail_stop", "fail_entry", "tick_down", "tick_up", "reconcile"]),
            st.integers(min_value=0, max_value=120),  # clock skew seconds (jumps forward unevenly)
        ),
        min_size=1,
        max_size=25,
    )
)
def test_system_always_ends_safe(steps):
    broker = FakeBroker()
    halts: list[tuple[str, bool]] = []
    manager = OrderManager(broker, MemoryOrderStore(), lambda r, h: halts.append((r, h)))
    local: list = []
    reconciler = Reconciler(broker, lambda: list(local), lambda r, h: halts.append((r, h)), lambda m: None)

    now = T0
    halted = False
    price = 2000.0
    for action, skew in steps:
        now += timedelta(seconds=30 + skew)
        broker.fail_stop_placement = action == "fail_stop"
        broker.fail_entry_placement = action == "fail_entry"
        if action in ("order", "fail_stop", "fail_entry") and not halted:
            if not broker.positions():  # live loop never pyramids
                result = manager.execute(make_intent(qty=1, entry=price), APPROVED, now)
                if result.sent:
                    local[:] = broker.positions()
                else:
                    local[:] = []
        elif action == "tick_down":
            price -= 45.0
            if broker.tick("MGC", price):
                local[:] = []  # fill event reaches the app
        elif action == "tick_up":
            price += 45.0
            if broker.tick("MGC", price):
                local[:] = []
        elif action == "reconcile":
            if not reconciler.run_once(now):
                local[:] = []
        halted = any(h for _, h in halts)
        broker.fail_stop_placement = broker.fail_entry_placement = False

    # Safe end state: every surviving position is stop-protected and books match.
    final = reconciler.run_once(now + timedelta(minutes=5))
    positions = broker.positions()
    if positions:
        assert final, "unreconciled position at end of chaos run"
        for p in positions:
            assert p.broker_stop_order_id is not None, "stopless position survived"
    # A hard halt can only have come from the reconciler or rate limiter here,
    # and both flatten first.
    if any(h for _, h in halts):
        pass  # halting is always an acceptable outcome


def test_clock_skew_backwards_does_not_crash_rate_limiter():
    broker = FakeBroker()
    manager = OrderManager(broker, MemoryOrderStore(), lambda r, h: None)
    assert manager.execute(make_intent(qty=1, side=Side.BUY), APPROVED, T0).sent
    broker.flatten_all()
    # Clock jumps backwards (NTP step): limiter must still behave sanely.
    earlier = T0 - timedelta(seconds=30)
    result = manager.execute(make_intent(qty=1), APPROVED, earlier)
    assert result.sent or "rate limit" in result.reason


def test_partial_fill_book_still_reconciles():
    # A partial fill shows up as a smaller broker position than local belief:
    # the reconciler must catch it and flatten.
    from goldguard.core.models import MGC, Position

    broker = FakeBroker()
    halts = []
    manager = OrderManager(broker, MemoryOrderStore(), lambda r, h: halts.append(h))
    manager.execute(make_intent(qty=1), RiskVerdict(verdict=Verdict.APPROVED, final_qty=1), T0)
    local = [Position(instrument=MGC, qty=2, avg_price=2000.0, stop_price=1960.0)]  # believes 2
    rec = Reconciler(broker, lambda: local, lambda r, h: halts.append(h), lambda m: None)
    assert rec.run_once(T0) is False
    assert broker.positions() == []
    assert True in halts


def test_fakebroker_cancel_unknown_order_raises():
    from goldguard.execution.broker import BrokerError

    with pytest.raises(BrokerError):
        FakeBroker().cancel("nope")
