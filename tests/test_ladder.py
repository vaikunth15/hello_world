"""Spec §3.4 — drawdown ladder state machine."""

from datetime import timedelta

from goldguard.core.models import SystemState
from goldguard.risk.ladder import DrawdownLadder

from .conftest import utc

T0 = utc(2026, 6, 9, 14, 0)


def make_ladder(equity: float = 100_000.0) -> DrawdownLadder:
    return DrawdownLadder(hwm=equity, day_start_equity=equity, current_day=T0.date())


def test_daily_loss_2pct_soft_halts():
    ladder = make_ladder()
    assert ladder.on_equity(98_500, T0) is SystemState.RUNNING
    assert ladder.on_equity(98_000, T0 + timedelta(hours=1)) is SystemState.SOFT_HALT


def test_soft_halt_expires_next_day():
    ladder = make_ladder()
    ladder.on_equity(98_000, T0)
    assert ladder.state is SystemState.SOFT_HALT
    assert ladder.on_equity(98_000, T0 + timedelta(days=1)) is SystemState.RUNNING
    # New daily reference: a further 2% from the new day-start halts again.
    assert ladder.on_equity(96_000, T0 + timedelta(days=1, hours=2)) is SystemState.SOFT_HALT


def test_drawdown_10pct_deleverages():
    ladder = make_ladder()
    ladder.on_equity(110_000, T0)  # raise HWM
    assert ladder.size_multiplier == 1.0
    ladder.on_equity(99_000, T0 + timedelta(days=1))  # 10% off 110k
    assert ladder.size_multiplier == 0.5


def test_deleverage_does_not_revert_on_recovery():
    ladder = make_ladder()
    ladder.on_equity(90_000, T0 + timedelta(days=1))
    assert ladder.size_multiplier == 0.5
    ladder.on_equity(99_500, T0 + timedelta(days=2))
    assert ladder.size_multiplier == 0.5  # only the locked-review path resets it


def test_drawdown_15pct_hard_halt_then_flatten_then_lock():
    ladder = make_ladder()
    ladder.on_equity(85_000, T0)
    assert ladder.state is SystemState.FLATTENING  # HARD_HALT -> FLATTENING immediately
    transitions = [e.payload for e in ladder.events if e.kind == "state_transition"]
    assert any(t.get("to") == SystemState.HARD_HALT for t in transitions)
    ladder.on_flattened(T0 + timedelta(minutes=5))
    assert ladder.state is SystemState.FLAT_LOCKED


def test_transitions_one_way_within_day():
    ladder = make_ladder()
    ladder.on_equity(85_000, T0)  # FLATTENING
    ladder.on_equity(99_000, T0 + timedelta(hours=1))  # recovery does not un-halt
    assert ladder.state is SystemState.FLATTENING


def test_unlock_requires_cooldown_review_and_timelock():
    ladder = make_ladder()
    ladder.on_equity(85_000, T0)
    ladder.on_flattened(T0)
    assert ladder.state is SystemState.FLAT_LOCKED

    # Too early: cooldown not elapsed.
    assert not ladder.request_unlock(T0 + timedelta(days=6), "reviewed by ops")
    # Missing signoff.
    assert not ladder.request_unlock(T0 + timedelta(days=8), "   ")
    # Valid request after cooldown...
    assert ladder.request_unlock(T0 + timedelta(days=8), "reviewed by ops")
    assert ladder.state is SystemState.FLAT_LOCKED  # still locked
    # ...cannot confirm before the 24h timelock...
    assert not ladder.confirm_unlock(T0 + timedelta(days=8, hours=23))
    # ...and unlocks after it.
    assert ladder.confirm_unlock(T0 + timedelta(days=9, hours=1))
    assert ladder.state is SystemState.RUNNING
    assert ladder.size_multiplier == 1.0


def test_confirm_without_request_fails():
    ladder = make_ladder()
    ladder.on_equity(85_000, T0)
    ladder.on_flattened(T0)
    assert not ladder.confirm_unlock(T0 + timedelta(days=30))


def test_operational_halt_paths():
    ladder = make_ladder()
    ladder.operational_halt(T0, "slippage breach", hard=False)
    assert ladder.state is SystemState.SOFT_HALT
    ladder.operational_halt(T0, "reconciler mismatch", hard=True)
    assert ladder.state is SystemState.FLATTENING


def test_unlock_request_in_running_state_is_noop():
    ladder = make_ladder()
    assert not ladder.request_unlock(T0, "reviewed")
