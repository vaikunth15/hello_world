"""Phase 4 DoD failure drills (spec §9) + execution-layer unit tests.

(a) kill the app with an open position -> the broker-side stop still fires;
(b) inject a position mismatch -> reconciler flattens + HARD_HALT + alert;
(c) order loop -> rate limiter halts at 5/min (and 20/day), order not sent.
"""

from datetime import timedelta

import pytest

from goldguard.core.models import MGC, Position, RiskVerdict, Side, Verdict
from goldguard.execution.broker import FakeBroker
from goldguard.execution.order_manager import (
    MAX_ORDERS_PER_DAY,
    MAX_ORDERS_PER_MINUTE,
    MemoryOrderStore,
    OrderManager,
)
from goldguard.execution.reconciler import Reconciler
from goldguard.execution.slippage import SlippageTracker

from .conftest import make_intent, utc

T0 = utc(2026, 6, 9, 15, 0)
APPROVED_1 = RiskVerdict(verdict=Verdict.APPROVED, final_qty=1)


class HaltRecorder:
    def __init__(self):
        self.calls: list[tuple[str, bool]] = []

    def __call__(self, reason: str, hard: bool) -> None:
        self.calls.append((reason, hard))

    @property
    def hard_halted(self) -> bool:
        return any(hard for _, hard in self.calls)

    @property
    def soft_halted(self) -> bool:
        return any(not hard for _, hard in self.calls)


def make_manager(broker=None, halt=None):
    broker = broker or FakeBroker()
    halt = halt or HaltRecorder()
    return OrderManager(broker, MemoryOrderStore(), halt), broker, halt


# ---------------------------------------------------------------- drill (a)

def test_drill_a_app_death_leaves_broker_stop_live():
    manager, broker, halt = make_manager()
    result = manager.execute(make_intent(side=Side.BUY, qty=1, entry=2000.0), APPROVED_1, T0)
    assert result.sent
    [pos] = broker.positions()
    assert pos.broker_stop_order_id is not None

    del manager  # the app dies; only the broker remains

    assert broker.tick("MGC", 1959.0)  # price crashes through the 1960 stop
    assert broker.positions() == []  # the broker-side stop closed it alone
    assert not halt.calls


# ---------------------------------------------------------------- drill (b)

def test_drill_b_position_mismatch_flattens_and_hard_halts():
    manager, broker, halt = make_manager()
    manager.execute(make_intent(qty=1), APPROVED_1, T0)
    alerts: list[str] = []

    # Local book wrongly believes there is no position.
    reconciler = Reconciler(broker, lambda: [], halt, alerts.append)
    assert reconciler.run_once(T0) is False
    assert broker.positions() == []
    assert broker.flatten_calls == 1
    assert halt.hard_halted
    assert alerts and "MISMATCH" in alerts[0]


def test_reconciler_matching_books_pass():
    manager, broker, halt = make_manager()
    manager.execute(make_intent(qty=1), APPROVED_1, T0)
    local = broker.positions()  # local book agrees
    reconciler = Reconciler(broker, lambda: local, halt, lambda m: pytest.fail(f"alert: {m}"))
    assert reconciler.run_once(T0) is True
    assert not halt.calls


def test_reconciler_resync_resolves_race():
    broker = FakeBroker()
    halt = HaltRecorder()
    local: list[Position] = []
    calls = {"n": 0}

    def lazy_local():
        # First read is stale; the re-sync read sees the fill.
        calls["n"] += 1
        return local if calls["n"] > 1 else []

    manager, _, _ = make_manager(broker, halt)
    manager.execute(make_intent(qty=1), APPROVED_1, T0)
    local.extend(broker.positions())
    reconciler = Reconciler(broker, lazy_local, halt, lambda m: pytest.fail(m))
    assert reconciler.run_once(T0) is True
    assert not halt.calls


# ---------------------------------------------------------------- drill (c)

def test_drill_c_rate_limiter_halts_at_5_per_minute():
    manager, broker, halt = make_manager()
    for i in range(MAX_ORDERS_PER_MINUTE):
        r = manager.execute(make_intent(qty=1), APPROVED_1, T0 + timedelta(seconds=i))
        assert r.sent, r.reason
        broker.flatten_all()  # avoid pyramiding-irrelevant broker state
    sixth = manager.execute(make_intent(qty=1), APPROVED_1, T0 + timedelta(seconds=10))
    assert not sixth.sent
    assert halt.hard_halted
    assert broker.flatten_calls == MAX_ORDERS_PER_MINUTE  # the 6th never reached the broker


def test_rate_limiter_daily_cap_20():
    manager, broker, halt = make_manager()
    sent = 0
    for i in range(MAX_ORDERS_PER_DAY + 1):
        r = manager.execute(
            make_intent(qty=1), APPROVED_1, T0 + timedelta(minutes=5 * i)
        )
        sent += r.sent
        broker.flatten_all()
    assert sent == MAX_ORDERS_PER_DAY
    assert halt.hard_halted


def test_rate_limiter_window_slides():
    manager, broker, _ = make_manager()
    for i in range(MAX_ORDERS_PER_MINUTE):
        assert manager.execute(make_intent(qty=1), APPROVED_1, T0 + timedelta(seconds=i)).sent
    # A minute later the per-minute window has rolled.
    assert manager.execute(make_intent(qty=1), APPROVED_1, T0 + timedelta(seconds=61)).sent


# ----------------------------------------------------- OrderManager gates

def test_rejected_verdict_never_reaches_broker():
    manager, broker, halt = make_manager()
    rejected = RiskVerdict(verdict=Verdict.REJECTED, reasons=["no"], final_qty=0)
    r = manager.execute(make_intent(qty=1), rejected, T0)
    assert not r.sent and broker.positions() == [] and not halt.calls


def test_entry_without_stop_rejected_double_enforcement():
    from goldguard.core.models import OrderIntent, OrderType

    manager, broker, _ = make_manager()
    bare = OrderIntent(instrument=MGC, side=Side.BUY, qty=1, type=OrderType.LIMIT, limit_price=2000.0)
    r = manager.execute(bare, APPROVED_1, T0)
    assert not r.sent and "double enforcement" in r.reason
    assert broker.positions() == []


def test_idempotency_same_order_not_resent():
    manager, broker, _ = make_manager()
    intent = make_intent(qty=1)
    assert manager.execute(intent, APPROVED_1, T0).sent
    again = manager.execute(intent, APPROVED_1, T0 + timedelta(seconds=1))
    assert not again.sent and "duplicate" in again.reason
    assert len(broker.positions()) == 1 and broker.positions()[0].qty == 1


def test_verdict_final_qty_overrides_intent_qty():
    manager, broker, _ = make_manager()
    modified = RiskVerdict(verdict=Verdict.MODIFIED, reasons=["capped"], final_qty=1)
    manager.execute(make_intent(qty=5), modified, T0)
    assert broker.positions()[0].qty == 1


def test_stop_placement_failure_flattens_and_soft_halts():
    broker = FakeBroker(fail_stop_placement=True)
    manager, _, halt = make_manager(broker)
    r = manager.execute(make_intent(qty=1), APPROVED_1, T0)
    assert not r.sent
    assert broker.positions() == []  # entry did not survive without a stop
    assert broker.flatten_calls == 1
    assert halt.soft_halted and not halt.hard_halted


def test_entry_placement_failure_soft_halts_safely():
    broker = FakeBroker(fail_entry_placement=True)
    manager, _, halt = make_manager(broker)
    r = manager.execute(make_intent(qty=1), APPROVED_1, T0)
    assert not r.sent and broker.positions() == [] and halt.soft_halted


# ----------------------------------------------------------- slippage

def test_slippage_breach_soft_halts_and_alerts():
    halt = HaltRecorder()
    alerts: list[str] = []
    tracker = SlippageTracker(modeled_cost_per_trade=1.0, halt=halt, alert=alerts.append)
    for i in range(20):
        tracker.record_fill(f"o{i}", MGC, expected_price=2000.0, fill_price=2000.3, qty=1)  # $3/trade
    assert halt.soft_halted
    assert alerts and "slippage breach" in alerts[0]
    assert tracker.stats()["rolling_avg_cost"] == pytest.approx(3.0)


def test_slippage_within_model_no_halt():
    halt = HaltRecorder()
    tracker = SlippageTracker(modeled_cost_per_trade=1.0, halt=halt, alert=lambda m: None)
    for i in range(40):
        tracker.record_fill(f"o{i}", MGC, expected_price=2000.0, fill_price=2000.1, qty=1)  # $1/trade
    assert not halt.calls


def test_duplicate_fill_messages_counted_once():
    halt = HaltRecorder()
    tracker = SlippageTracker(modeled_cost_per_trade=1.0, halt=halt, alert=lambda m: None)
    for _ in range(50):
        tracker.record_fill("same-order", MGC, expected_price=2000.0, fill_price=2010.0, qty=1)
    assert tracker.stats()["window"] == 1
    assert not halt.calls
