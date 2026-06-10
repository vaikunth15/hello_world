"""Indicator math against hand-checked values."""

from datetime import datetime, timedelta, timezone

import pytest

from goldguard.core.models import Bar, Timeframe
from goldguard.signals.indicators import adx, atr, donchian_high, donchian_low, ema, ema_series


def make_bars(rows: list[tuple[float, float, float, float]]) -> list[Bar]:
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        Bar(timestamp=t0 + timedelta(days=i), timeframe=Timeframe.DAILY, open=o, high=h, low=l, close=c)
        for i, (o, h, l, c) in enumerate(rows)
    ]


def test_ema_seeded_with_sma():
    # EMA(3) of [1..5]: seed SMA=2, then k=0.5: 3, 4.
    assert ema_series([1, 2, 3, 4, 5], 3) == [2.0, 3.0, 4.0]
    assert ema([1, 2, 3, 4, 5], 3) == 4.0


def test_ema_requires_enough_values():
    with pytest.raises(ValueError):
        ema([1.0, 2.0], 3)


def test_atr_constant_range():
    # Every bar has range 2 and no gaps: ATR must be exactly 2.
    bars = make_bars([(10, 11, 9, 10)] * 20)
    assert atr(bars, 14) == pytest.approx(2.0)


def test_atr_includes_gaps():
    # A gap day: TR = |high - prev_close| dominates.
    rows = [(10.0, 11.0, 9.0, 10.0)] * 15 + [(20.0, 21.0, 19.0, 20.0)]
    bars = make_bars(rows)
    # Last TR = max(2, |21-10|, |19-10|) = 11; Wilder: (2*13 + 11)/14.
    assert atr(bars, 14) == pytest.approx((2 * 13 + 11) / 14)


def test_atr_requires_n_plus_one_bars():
    with pytest.raises(ValueError):
        atr(make_bars([(10, 11, 9, 10)] * 14), 14)


def test_donchian_channels():
    rows = [(10, 12, 8, 10), (10, 15, 9, 14), (14, 16, 13, 15), (15, 17, 11, 12)]
    bars = make_bars(rows)
    assert donchian_high(bars, 3) == 17
    assert donchian_low(bars, 3) == 9
    assert donchian_high(bars, 2) == 17
    assert donchian_low(bars, 2) == 11


def test_adx_strong_trend_is_high_flat_market_is_low():
    up = make_bars([(100 + i, 101 + i, 99 + i, 100.5 + i) for i in range(40)])
    flat = make_bars([(100, 101, 99, 100), (100, 101, 99, 100.2)] * 20)
    assert adx(up, 14) > 60
    assert adx(flat, 14) < 15


def test_adx_requires_enough_bars():
    with pytest.raises(ValueError):
        adx(make_bars([(10, 11, 9, 10)] * 20), 14)
