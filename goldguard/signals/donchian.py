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


def channel_state(bars: list[Bar]) -> Direction:
    """Replay the raw channel system (no regime filter) over the history."""
    state = Direction.FLAT
    for i in range(ENTRY_WINDOW, len(bars)):
        window = bars[:i]  # everything before today's bar
        close = bars[i].close
        if state is Direction.LONG and close <= donchian_low(window, EXIT_WINDOW):
            state = Direction.FLAT
        elif state is Direction.SHORT and close >= donchian_high(window, EXIT_WINDOW):
            state = Direction.FLAT
        if state is Direction.FLAT:
            if close > donchian_high(window, ENTRY_WINDOW):
                state = Direction.LONG
            elif close < donchian_low(window, ENTRY_WINDOW):
                state = Direction.SHORT
    return state


class DonchianTrend:
    strategy_id = "donchian_55_20"

    def generate(self, bars: list[Bar], macro: MacroState) -> Signal:
        if len(bars) < ENTRY_WINDOW + 1:
            return self._flat(bars)
        state = channel_state(bars)
        if state is Direction.LONG and not macro.long_regime_ok():
            state = Direction.FLAT
        elif state is Direction.SHORT and not macro.short_regime_ok():
            state = Direction.FLAT
        return Signal(
            direction=state,
            strength=1.0 if state is not Direction.FLAT else 0.0,
            strategy_id=self.strategy_id,
            timestamp=bars[-1].timestamp,
            proposed_stop_atr_multiple=STOP_ATR_MULTIPLE,
        )

    def _flat(self, bars: list[Bar]) -> Signal:
        return Signal(
            direction=Direction.FLAT,
            strength=0.0,
            strategy_id=self.strategy_id,
            timestamp=bars[-1].timestamp,
            proposed_stop_atr_multiple=STOP_ATR_MULTIPLE,
        )
