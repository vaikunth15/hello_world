"""Walk-forward harness (spec §7): train 3 years, test 1 year, roll annually.

On each train window we pick the Donchian entry window (small, honest grid)
that maximizes total return, then evaluate it out-of-sample on the following
test year. Only the concatenated TEST segments count.
"""

from __future__ import annotations

from goldguard.backtest.costs import CostModel
from goldguard.backtest.engine import Backtester, WARMUP_BARS
from goldguard.backtest.metrics import summarize
from goldguard.core.models import Bar
from goldguard.risk.config import RiskConfig
from goldguard.signals.donchian import DonchianTrend

TRADING_DAYS_PER_YEAR = 252
TRAIN_YEARS, TEST_YEARS = 3, 1
ENTRY_GRID = [40, 55, 70]


def _run(bars: list[Bar], entry_window: int, costs: CostModel) -> dict:
    strategy = DonchianTrend(entry_window=entry_window)
    result = Backtester(strategy, RiskConfig(), costs).run(bars)
    return summarize(result)


def walk_forward(bars: list[Bar], costs: CostModel | None = None) -> dict:
    costs = costs or CostModel()
    train_n = TRAIN_YEARS * TRADING_DAYS_PER_YEAR
    test_n = TEST_YEARS * TRADING_DAYS_PER_YEAR
    folds = []
    start = 0
    while start + train_n + test_n <= len(bars):
        train = bars[start : start + train_n]
        # Include warmup history so the test window trades from day one.
        test = bars[start + train_n - WARMUP_BARS : start + train_n + test_n]
        scored = [(entry, _run(train, entry, costs)["total_return_pct"]) for entry in ENTRY_GRID]
        best_entry = max(scored, key=lambda s: s[1])[0]
        test_summary = _run(test, best_entry, costs)
        folds.append(
            {
                "train_start": train[0].timestamp.date().isoformat(),
                "test_start": test[WARMUP_BARS].timestamp.date().isoformat(),
                "test_end": test[-1].timestamp.date().isoformat(),
                "chosen_entry_window": best_entry,
                "train_scores": dict(scored),
                "test": test_summary,
            }
        )
        start += test_n  # roll annually
    oos_returns = [f["test"]["total_return_pct"] for f in folds]
    return {
        "folds": folds,
        "oos_mean_annual_return_pct": round(sum(oos_returns) / len(oos_returns), 2) if folds else None,
        "oos_positive_years": sum(1 for r in oos_returns if r > 0),
        "oos_years": len(folds),
    }
