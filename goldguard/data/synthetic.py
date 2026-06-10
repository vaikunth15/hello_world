"""Deterministic synthetic gold-like daily series.

Used by golden-file tests and as a fallback dataset for the backtest harness
when no real continuous-contract CSV has been provided. Seeded Mersenne
Twister: same seed, same bars, every run.
"""

from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta, timezone

from goldguard.core.models import Bar, Timeframe


def synthetic_gold_bars(
    n_days: int = 1500, seed: int = 7, start: date = date(2018, 1, 2), start_price: float = 1300.0
) -> list[Bar]:
    rng = random.Random(seed)
    bars: list[Bar] = []
    price = start_price
    d = start
    drift = 0.0
    for i in range(n_days):
        while d.weekday() >= 5:  # skip weekends
            d += timedelta(days=1)
        if i % 120 == 0:  # new trend regime roughly every 6 months
            drift = rng.choice([-0.0008, 0.0, 0.0004, 0.001])
        ret = rng.gauss(drift, 0.009)
        o = price
        c = max(1.0, price * (1 + ret))
        spread = abs(rng.gauss(0, 0.004)) * price
        h = max(o, c) + spread
        lo = min(o, c) - spread
        bars.append(
            Bar(
                timestamp=datetime.combine(d, time(17, 0), tzinfo=timezone.utc),
                timeframe=Timeframe.DAILY,
                open=round(o, 1),
                high=round(h, 1),
                low=round(lo, 1),
                close=round(c, 1),
                volume=float(rng.randint(10_000, 60_000)),
            )
        )
        price = c
        d += timedelta(days=1)
    return bars


def synthetic_macro_series(n: int, seed: int, start: date, base: float, vol: float) -> list[tuple[date, float]]:
    rng = random.Random(seed)
    out: list[tuple[date, float]] = []
    d, v = start, base
    for _ in range(n):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        v += rng.gauss(0, vol)
        out.append((d, round(v, 4)))
        d += timedelta(days=1)
    return out
