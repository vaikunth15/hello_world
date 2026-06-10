"""Drawdown ladder state machine (spec §3.4).

Invariants:
- Daily loss >= 2% of day-start equity -> SOFT_HALT for the rest of the day.
- Drawdown from high-water mark >= 10% -> size multiplier 0.5 (deleverage).
  The multiplier never increases intraday and only resets via the same
  timelocked re-enable path as un-halting.
- Drawdown >= 15% -> HARD_HALT, then FLATTENING, ending in FLAT_LOCKED.
- Transitions are one-way within a day; un-halting always goes through a
  7-day cooldown plus an explicit, timelocked manual re-enable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from goldguard.core.models import AuditEvent, SystemState

DAILY_LOSS_HALT_PCT = 0.02
DELEVERAGE_DD_PCT = 0.10
HARD_HALT_DD_PCT = 0.15
DELEVERAGE_FACTOR = 0.5
COOLDOWN_DAYS = 7
UNLOCK_TIMELOCK_HOURS = 24

_SEVERITY = {
    SystemState.RUNNING: 0,
    SystemState.SOFT_HALT: 1,
    SystemState.HARD_HALT: 2,
    SystemState.FLATTENING: 3,
    SystemState.FLAT_LOCKED: 4,
}


@dataclass
class DrawdownLadder:
    hwm: float
    day_start_equity: float
    current_day: date
    state: SystemState = SystemState.RUNNING
    size_multiplier: float = 1.0
    locked_since: datetime | None = None
    unlock_requested_at: datetime | None = None
    events: list[AuditEvent] = field(default_factory=list)

    def _transition(self, new_state: SystemState, now: datetime, reason: str) -> None:
        # One-way within a day: never move to a less severe state here.
        if _SEVERITY[new_state] <= _SEVERITY[self.state]:
            return
        self.events.append(
            AuditEvent(
                timestamp=now,
                kind="state_transition",
                payload={"from": self.state, "to": new_state, "reason": reason},
            )
        )
        self.state = new_state
        if new_state is SystemState.FLAT_LOCKED:
            self.locked_since = now

    def on_new_day(self, equity: float, now: datetime) -> None:
        """Roll the daily window. SOFT_HALT from a daily loss expires; halts
        from drawdown or operational failures do not."""
        self.current_day = now.date()
        self.day_start_equity = equity
        if self.state is SystemState.SOFT_HALT:
            self.state = SystemState.RUNNING
            self.events.append(
                AuditEvent(timestamp=now, kind="state_transition",
                           payload={"from": "SOFT_HALT", "to": "RUNNING", "reason": "new trading day"})
            )

    def on_equity(self, equity: float, now: datetime) -> SystemState:
        if now.date() != self.current_day:
            self.on_new_day(equity, now)
        self.hwm = max(self.hwm, equity)

        daily_loss = (self.day_start_equity - equity) / self.day_start_equity
        drawdown = (self.hwm - equity) / self.hwm

        if drawdown >= HARD_HALT_DD_PCT:
            self._transition(SystemState.HARD_HALT, now, f"drawdown {drawdown:.1%} >= {HARD_HALT_DD_PCT:.0%}")
            self._transition(SystemState.FLATTENING, now, "hard halt requires flatten")
        if drawdown >= DELEVERAGE_DD_PCT:
            if self.size_multiplier > DELEVERAGE_FACTOR:
                self.size_multiplier = DELEVERAGE_FACTOR
                self.events.append(
                    AuditEvent(timestamp=now, kind="state_transition",
                               payload={"deleverage": DELEVERAGE_FACTOR,
                                        "reason": f"drawdown {drawdown:.1%} >= {DELEVERAGE_DD_PCT:.0%}"})
                )
        if daily_loss >= DAILY_LOSS_HALT_PCT:
            self._transition(SystemState.SOFT_HALT, now, f"daily loss {daily_loss:.1%} >= {DAILY_LOSS_HALT_PCT:.0%}")
        return self.state

    def on_flattened(self, now: datetime) -> None:
        """Called when FLATTENING completes: all positions confirmed closed."""
        if self.state is SystemState.FLATTENING:
            self._transition(SystemState.FLAT_LOCKED, now, "flatten complete after hard halt")

    def operational_halt(self, now: datetime, reason: str, hard: bool) -> None:
        """Externally triggered halt (rate limiter, reconciler, manual HALT).
        Halting is always allowed instantly — stricter is never delayed."""
        self._transition(SystemState.HARD_HALT if hard else SystemState.SOFT_HALT, now, reason)
        if hard:
            self._transition(SystemState.FLATTENING, now, reason)

    def request_unlock(self, now: datetime, manual_review_signoff: str) -> bool:
        """Step 1 of leaving FLAT_LOCKED: file a manual review. Only valid
        after the 7-day cooldown. The unlock itself is timelocked a further
        24 hours (spec §3.4: manual review + cooldown + timelocked re-enable).
        There is no faster path."""
        if self.state is not SystemState.FLAT_LOCKED:
            return False
        if not manual_review_signoff.strip():
            return False
        assert self.locked_since is not None
        if now < self.locked_since + timedelta(days=COOLDOWN_DAYS):
            return False
        self.unlock_requested_at = now
        self.events.append(
            AuditEvent(timestamp=now, kind="state_transition",
                       payload={"unlock_requested": True, "signoff": manual_review_signoff,
                                "effective_at": (now + timedelta(hours=UNLOCK_TIMELOCK_HOURS)).isoformat()})
        )
        return True

    def confirm_unlock(self, now: datetime) -> bool:
        """Step 2: activate a previously requested unlock once its 24h
        timelock has elapsed."""
        if self.state is not SystemState.FLAT_LOCKED or self.unlock_requested_at is None:
            return False
        if now < self.unlock_requested_at + timedelta(hours=UNLOCK_TIMELOCK_HOURS):
            return False
        self.events.append(
            AuditEvent(timestamp=now, kind="state_transition",
                       payload={"from": "FLAT_LOCKED", "to": "RUNNING", "reason": "cooldown + timelock elapsed"})
        )
        self.state = SystemState.RUNNING
        self.size_multiplier = 1.0
        self.hwm = self.day_start_equity  # reset reference after review
        self.locked_since = None
        self.unlock_requested_at = None
        return True
