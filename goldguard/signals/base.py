"""Strategy interface (spec §4): pure functions, no I/O. ``generate`` is the
desired-direction function: given the full daily-bar history and the current
macro snapshot, it returns the direction the system wants to hold AFTER
today's close. The caller (live scheduler or backtester) diffs that against
the actual position to derive entries/exits, then the risk engine vets them.
"""

from __future__ import annotations

from typing import Protocol

from goldguard.core.models import Bar, Signal
from goldguard.data.macro import MacroState


class Strategy(Protocol):
    strategy_id: str

    def generate(self, bars: list[Bar], macro: MacroState) -> Signal: ...
