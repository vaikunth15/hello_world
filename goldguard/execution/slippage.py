"""Slippage tracking (spec §5): expected vs fill per order, rolling stats.
If realized cost per trade exceeds 2x the modeled cost over the last 20
trades, SOFT_HALT and alert — the cost model is lying and so is the backtest.
"""

from __future__ import annotations

from collections import deque
from typing import Callable

from goldguard.core.models import Instrument
from goldguard.execution.order_manager import HaltFn

WINDOW = 20
BREACH_MULTIPLE = 2.0


class SlippageTracker:
    def __init__(self, modeled_cost_per_trade: float, halt: HaltFn, alert: Callable[[str], None]):
        if modeled_cost_per_trade <= 0:
            raise ValueError("modeled cost must be positive")
        self._modeled = modeled_cost_per_trade
        self._halt = halt
        self._alert = alert
        self._costs: deque[float] = deque(maxlen=WINDOW)
        self._seen_order_ids: set[str] = set()

    def record_fill(self, order_id: str, instrument: Instrument,
                    expected_price: float, fill_price: float, qty: int) -> None:
        if order_id in self._seen_order_ids:
            return  # duplicate fill message — count once
        self._seen_order_ids.add(order_id)
        cost = abs(fill_price - expected_price) * qty * instrument.point_value
        self._costs.append(cost)
        if len(self._costs) == WINDOW and self.rolling_avg() > BREACH_MULTIPLE * self._modeled:
            self._alert(
                f"slippage breach: avg ${self.rolling_avg():.2f}/trade over last {WINDOW} "
                f"vs modeled ${self._modeled:.2f}"
            )
            self._halt("realized slippage > 2x modeled over last 20 trades", False)

    def rolling_avg(self) -> float:
        return sum(self._costs) / len(self._costs) if self._costs else 0.0

    def stats(self) -> dict:
        return {
            "window": len(self._costs),
            "rolling_avg_cost": round(self.rolling_avg(), 4),
            "modeled_cost": self._modeled,
            "breach_threshold": BREACH_MULTIPLE * self._modeled,
        }
