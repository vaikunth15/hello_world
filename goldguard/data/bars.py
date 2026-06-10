"""Bar ingestion. CSV/historical first (spec Phase 2); the broker feed
implements the same ``BarSource`` protocol later.

CSV format: ``timestamp,open,high,low,close,volume`` with ISO-8601
timezone-aware timestamps. Bars must be strictly increasing in time; we
refuse silently broken data rather than trade on it.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Protocol

from goldguard.core.models import Bar, Timeframe


class BarSource(Protocol):
    def daily_bars(self, symbol: str, limit: int) -> list[Bar]: ...


def load_bars_csv(path: Path, timeframe: Timeframe = Timeframe.DAILY) -> list[Bar]:
    bars: list[Bar] = []
    with path.open() as f:
        for row in csv.DictReader(f):
            ts = datetime.fromisoformat(row["timestamp"])
            if ts.tzinfo is None:
                raise ValueError(f"naive timestamp in {path}: {row['timestamp']}")
            bars.append(
                Bar(
                    timestamp=ts,
                    timeframe=timeframe,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row.get("volume") or 0.0),
                )
            )
    validate_bars(bars)
    return bars


def validate_bars(bars: list[Bar]) -> None:
    for prev, cur in zip(bars, bars[1:]):
        if cur.timestamp <= prev.timestamp:
            raise ValueError(f"bars not strictly increasing at {cur.timestamp}")
    for b in bars:
        if not (b.low <= b.open <= b.high and b.low <= b.close <= b.high and b.low <= b.high):
            raise ValueError(f"inconsistent OHLC at {b.timestamp}")
