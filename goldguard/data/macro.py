"""Macro regime inputs (spec §4): 10Y TIPS real yield (FRED ``DFII10``) and a
dollar index proxy (FRED ``DTWEXBGS``). Adapters return plain (date, value)
series; ``build_macro_state`` reduces them to the snapshot the strategies
consume. Strategies never see the adapter — they are pure functions.
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from typing import Protocol

from goldguard.core.models import Frozen

REAL_YIELD_SERIES = "DFII10"
DXY_SERIES = "DTWEXBGS"


class MacroState(Frozen):
    """Snapshot used by strategies. ``None`` means insufficient data — the
    regime filter then fails closed (no trade)."""

    real_yield_20d_change: float | None = None
    dxy: float | None = None
    dxy_50d_ma: float | None = None

    def long_regime_ok(self) -> bool:
        falling_yields = self.real_yield_20d_change is not None and self.real_yield_20d_change < 0
        weak_dollar = (
            self.dxy is not None and self.dxy_50d_ma is not None and self.dxy < self.dxy_50d_ma
        )
        return falling_yields or weak_dollar

    def short_regime_ok(self) -> bool:
        rising_yields = self.real_yield_20d_change is not None and self.real_yield_20d_change > 0
        strong_dollar = (
            self.dxy is not None and self.dxy_50d_ma is not None and self.dxy > self.dxy_50d_ma
        )
        return rising_yields or strong_dollar


class MacroSource(Protocol):
    def series(self, series_id: str, limit: int) -> list[tuple[date, float]]: ...


class CsvMacroSource:
    """Reads ``date,value`` CSVs named ``<SERIES_ID>.csv`` from a directory."""

    def __init__(self, directory: Path):
        self._dir = directory

    def series(self, series_id: str, limit: int) -> list[tuple[date, float]]:
        out: list[tuple[date, float]] = []
        with (self._dir / f"{series_id}.csv").open() as f:
            for row in csv.DictReader(f):
                if row["value"] in ("", "."):  # FRED encodes missing as "."
                    continue
                out.append((date.fromisoformat(row["date"]), float(row["value"])))
        out.sort()
        return out[-limit:]


def build_macro_state(
    real_yield: list[tuple[date, float]], dxy: list[tuple[date, float]]
) -> MacroState:
    ry_change = real_yield[-1][1] - real_yield[-21][1] if len(real_yield) >= 21 else None
    if len(dxy) >= 50:
        dxy_last = dxy[-1][1]
        dxy_ma = sum(v for _, v in dxy[-50:]) / 50
    else:
        dxy_last = dxy_ma = None
    return MacroState(real_yield_20d_change=ry_change, dxy=dxy_last, dxy_50d_ma=dxy_ma)
