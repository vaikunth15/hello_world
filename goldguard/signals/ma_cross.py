"""MA Cross benchmark strategy (spec §4): 20/50 EMA cross on daily bars,
traded only while ADX(14) > 20. Pure desired-direction function; the macro
snapshot is accepted for interface parity but unused."""

from __future__ import annotations

from goldguard.core.models import Bar, Direction, Signal
from goldguard.data.macro import MacroState
from goldguard.signals.indicators import adx, ema

FAST, SLOW = 20, 50
ADX_PERIOD, ADX_MIN = 14, 20.0
STOP_ATR_MULTIPLE = 2.0
MIN_BARS = max(SLOW, 2 * ADX_PERIOD + 1)


class MaCross:
    strategy_id = "ema_20_50_adx"

    def generate(self, bars: list[Bar], macro: MacroState) -> Signal:
        direction = Direction.FLAT
        if len(bars) >= MIN_BARS:
            closes = [b.close for b in bars]
            fast, slow = ema(closes, FAST), ema(closes, SLOW)
            trending = adx(bars, ADX_PERIOD) > ADX_MIN
            if trending and fast > slow:
                direction = Direction.LONG
            elif trending and fast < slow:
                direction = Direction.SHORT
        return Signal(
            direction=direction,
            strength=1.0 if direction is not Direction.FLAT else 0.0,
            strategy_id=self.strategy_id,
            timestamp=bars[-1].timestamp,
            proposed_stop_atr_multiple=STOP_ATR_MULTIPLE,
        )
