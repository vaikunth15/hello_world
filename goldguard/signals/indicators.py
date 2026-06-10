"""Deterministic indicator math. Plain floats, no numpy — auditability over
speed at daily-bar volumes."""

from __future__ import annotations

from goldguard.core.models import Bar


def true_range(prev_close: float, bar: Bar) -> float:
    return max(bar.high - bar.low, abs(bar.high - prev_close), abs(bar.low - prev_close))


def atr(bars: list[Bar], n: int = 14) -> float:
    """Wilder ATR over the full history; requires at least n+1 bars."""
    if len(bars) < n + 1:
        raise ValueError(f"ATR({n}) needs at least {n + 1} bars, got {len(bars)}")
    trs = [true_range(bars[i - 1].close, bars[i]) for i in range(1, len(bars))]
    value = sum(trs[:n]) / n
    for tr in trs[n:]:
        value = (value * (n - 1) + tr) / n
    return value


def ema_series(values: list[float], n: int) -> list[float]:
    """EMA seeded with the SMA of the first n values; output aligns with
    ``values`` from index n-1 onward."""
    if len(values) < n:
        raise ValueError(f"EMA({n}) needs at least {n} values")
    out = [sum(values[:n]) / n]
    k = 2 / (n + 1)
    for v in values[n:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def ema(values: list[float], n: int) -> float:
    return ema_series(values, n)[-1]


def donchian_high(bars: list[Bar], n: int) -> float:
    """Highest high of the LAST n bars (callers pass the window excluding today)."""
    return max(b.high for b in bars[-n:])


def donchian_low(bars: list[Bar], n: int) -> float:
    return min(b.low for b in bars[-n:])


def adx(bars: list[Bar], n: int = 14) -> float:
    """Wilder ADX. Requires at least 2n+1 bars."""
    if len(bars) < 2 * n + 1:
        raise ValueError(f"ADX({n}) needs at least {2 * n + 1} bars, got {len(bars)}")
    plus_dm, minus_dm, trs = [], [], []
    for i in range(1, len(bars)):
        up = bars[i].high - bars[i - 1].high
        down = bars[i - 1].low - bars[i].low
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        trs.append(true_range(bars[i - 1].close, bars[i]))

    def wilder_smooth(xs: list[float]) -> list[float]:
        out = [sum(xs[:n])]
        for x in xs[n:]:
            out.append(out[-1] - out[-1] / n + x)
        return out

    str_, spd, smd = wilder_smooth(trs), wilder_smooth(plus_dm), wilder_smooth(minus_dm)
    dxs = []
    for tr_s, pd_s, md_s in zip(str_, spd, smd):
        if tr_s == 0:
            dxs.append(0.0)
            continue
        pdi, mdi = 100 * pd_s / tr_s, 100 * md_s / tr_s
        dxs.append(0.0 if pdi + mdi == 0 else 100 * abs(pdi - mdi) / (pdi + mdi))
    adx_val = sum(dxs[:n]) / n
    for dx in dxs[n:]:
        adx_val = (adx_val * (n - 1) + dx) / n
    return adx_val
