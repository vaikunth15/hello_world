"""Donchian Trend (primary strategy, spec §4).

Channel logic, replayed deterministically over the full history so the
function stays pure and stateless:
- enter long when the close breaks the prior 55-day high; exit on the prior
  20-day low (inverse for shorts).
- Stop: 2 x ATR(14).
- Regime filter (applied to the OUTPUT, never to exits): longs only if the
  10Y real yield's 20-day change < 0 OR DXY is below its 50-day MA; shorts
  on the inverse. While the filter fails the strategy emits FLAT, so an
  unfiltered channel position is never opened and an open one is closed.
"""

from __future__ import annotations

from goldguard.core.models import Bar, Direction, Signal
from goldguard.data.macro import MacroState
from goldguard.signals.indicators import donchian_high, donchian_low

ENTRY_WINDOW = 55
EXIT_WINDOW = 20
STOP_ATR_MULTIPLE = 2.0


def channel_state(
    bars: list[Bar],
    entry_window: int = ENTRY_WINDOW,
    exit_window: int = EXIT_WINDOW,
    start_index: int | None = None,
    start_state: Direction = Direction.FLAT,
) -> Direction:
    """Replay the raw channel system (no regime filter) over the history.

    ``start_index``/``start_state`` resume a replay whose prefix outcome is
    already known — an optimization hook for the memoizing wrapper below; the
    result is identical to a full replay.
    """
    state = start_state
    for i in range(start_index if start_index is not None else entry_window, len(bars)):
        window = bars[:i]  # everything before today's bar
        close = bars[i].close
        if state is Direction.LONG and close <= donchian_low(window, exit_window):
            state = Direction.FLAT
        elif state is Direction.SHORT and close >= donchian_high(window, exit_window):
            state = Direction.FLAT
        if state is Direction.FLAT:
            if close > donchian_high(window, entry_window):
                state = Direction.LONG
            elif close < donchian_low(window, entry_window):
                state = Direction.SHORT
    return state


class DonchianTrend:
    def __init__(
        self,
        entry_window: int = ENTRY_WINDOW,
        exit_window: int = EXIT_WINDOW,
        stop_atr_multiple: float = STOP_ATR_MULTIPLE,
    ):
        self.entry_window = entry_window
        self.exit_window = exit_window
        self.stop_atr_multiple = stop_atr_multiple
        self.strategy_id = f"donchian_{entry_window}_{exit_window}"
        # Memoized replay position: (bars consumed, last timestamp, state).
        # Purely an optimization — the emitted Signal is a function of the
        # inputs alone, and any history mismatch falls back to a full replay.
        self._replay: tuple[int, object, Direction] | None = None

    def _channel_state(self, bars: list[Bar]) -> Direction:
        if self._replay is not None:
            count, last_ts, state = self._replay
            if (
                self.entry_window <= count <= len(bars)
                and bars[count - 1].timestamp == last_ts
            ):
                state = channel_state(
                    bars, self.entry_window, self.exit_window,
                    start_index=count, start_state=state,
                )
            else:
                state = channel_state(bars, self.entry_window, self.exit_window)
        else:
            state = channel_state(bars, self.entry_window, self.exit_window)
        self._replay = (len(bars), bars[-1].timestamp, state)
        return state

    def generate(self, bars: list[Bar], macro: MacroState) -> Signal:
        if len(bars) < self.entry_window + 1:
            return self._flat(bars)
        state = self._channel_state(bars)
        if state is Direction.LONG and not macro.long_regime_ok():
            state = Direction.FLAT
        elif state is Direction.SHORT and not macro.short_regime_ok():
            state = Direction.FLAT
        return Signal(
            direction=state,
            strength=1.0 if state is not Direction.FLAT else 0.0,
            strategy_id=self.strategy_id,
            timestamp=bars[-1].timestamp,
            proposed_stop_atr_multiple=self.stop_atr_multiple,
        )

    def _flat(self, bars: list[Bar]) -> Signal:
        return Signal(
            direction=Direction.FLAT,
            strength=0.0,
            strategy_id=self.strategy_id,
            timestamp=bars[-1].timestamp,
            proposed_stop_atr_multiple=self.stop_atr_multiple,
        )
