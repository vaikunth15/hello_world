"""Strategy behavior + the Phase 2 DoD golden-file test: same input bars
always produce the same signals."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from goldguard.core.models import Bar, Direction, Timeframe
from goldguard.data.macro import MacroState
from goldguard.data.synthetic import synthetic_gold_bars
from goldguard.signals.donchian import DonchianTrend
from goldguard.signals.ma_cross import MaCross

GOLDEN = Path(__file__).parent / "golden" / "signals.json"

LONG_REGIME = MacroState(real_yield_20d_change=-0.2, dxy=100.0, dxy_50d_ma=102.0)
SHORT_REGIME = MacroState(real_yield_20d_change=0.2, dxy=104.0, dxy_50d_ma=102.0)
NO_REGIME = MacroState()


def flat_then(extra: list[tuple[float, float, float, float]], n_flat: int = 60) -> list[Bar]:
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [(100.0, 101.0, 99.0, 100.0)] * n_flat + extra
    return [
        Bar(timestamp=t0 + timedelta(days=i), timeframe=Timeframe.DAILY, open=o, high=h, low=l, close=c)
        for i, (o, h, l, c) in enumerate(rows)
    ]


def test_donchian_long_breakout_with_regime():
    bars = flat_then([(100.0, 111.0, 100.0, 110.0)])
    sig = DonchianTrend().generate(bars, LONG_REGIME)
    assert sig.direction is Direction.LONG
    assert sig.proposed_stop_atr_multiple == 2.0
    assert sig.strategy_id == "donchian_55_20"


def test_donchian_breakout_blocked_by_regime():
    bars = flat_then([(100.0, 111.0, 100.0, 110.0)])
    assert DonchianTrend().generate(bars, NO_REGIME).direction is Direction.FLAT
    assert DonchianTrend().generate(bars, SHORT_REGIME).direction is Direction.FLAT


def test_donchian_short_breakout():
    bars = flat_then([(100.0, 100.0, 89.0, 90.0)])
    assert DonchianTrend().generate(bars, SHORT_REGIME).direction is Direction.SHORT
    assert DonchianTrend().generate(bars, LONG_REGIME).direction is Direction.FLAT


def test_donchian_exit_on_20_day_low():
    rising = [(100.0 + i, 101.5 + i, 99.5 + i, 101.0 + i) for i in range(25)]
    bars = flat_then(rising)
    assert DonchianTrend().generate(bars, LONG_REGIME).direction is Direction.LONG
    # Crash through the prior 20-day low (min low of last 20 rising bars).
    low20 = min(b.low for b in bars[-20:])
    crash = (bars[-1].close, bars[-1].close, low20 - 5, low20 - 4)
    bars2 = flat_then(rising + [crash])
    assert DonchianTrend().generate(bars2, LONG_REGIME).direction is Direction.FLAT


def test_donchian_insufficient_history_is_flat():
    bars = flat_then([], n_flat=30)
    assert DonchianTrend().generate(bars, LONG_REGIME).direction is Direction.FLAT


def test_ma_cross_trend_and_flat():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    up = [
        Bar(timestamp=t0 + timedelta(days=i), timeframe=Timeframe.DAILY,
            open=100.0 + i, high=101.5 + i, low=99.5 + i, close=101.0 + i)
        for i in range(60)
    ]
    sig = MaCross().generate(up, NO_REGIME)
    assert sig.direction is Direction.LONG

    chop = [
        Bar(timestamp=t0 + timedelta(days=i), timeframe=Timeframe.DAILY,
            open=100.0, high=101.0, low=99.0, close=100.0 + (0.2 if i % 2 else -0.2))
        for i in range(60)
    ]
    assert MaCross().generate(chop, NO_REGIME).direction is Direction.FLAT  # ADX filter


def test_ma_cross_short():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    down = [
        Bar(timestamp=t0 + timedelta(days=i), timeframe=Timeframe.DAILY,
            open=200.0 - i, high=200.5 - i, low=198.5 - i, close=199.0 - i)
        for i in range(60)
    ]
    assert MaCross().generate(down, NO_REGIME).direction is Direction.SHORT


def compute_golden() -> dict:
    """Signals for the last 120 days of the seeded synthetic series, for both
    strategies, under a fixed favorable regime."""
    bars = synthetic_gold_bars(n_days=400, seed=7)
    donchian, ma = DonchianTrend(), MaCross()
    out = {"donchian_55_20": [], "ema_20_50_adx": []}
    for i in range(len(bars) - 120, len(bars)):
        prefix = bars[: i + 1]
        out["donchian_55_20"].append(donchian.generate(prefix, LONG_REGIME).direction.value)
        out["ema_20_50_adx"].append(ma.generate(prefix, NO_REGIME).direction.value)
    return out


def test_golden_file_signals_are_reproducible():
    assert GOLDEN.exists(), "golden file missing — run scripts/update_golden.py and review the diff"
    assert compute_golden() == json.loads(GOLDEN.read_text())
