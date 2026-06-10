"""Performance metrics for backtest results."""

from __future__ import annotations

import math

from goldguard.backtest.engine import BacktestResult


def max_drawdown(curve: list[tuple[object, float]]) -> float:
    peak, worst = float("-inf"), 0.0
    for _, v in curve:
        peak = max(peak, v)
        worst = max(worst, (peak - v) / peak)
    return worst


def cagr(result: BacktestResult) -> float:
    if not result.equity_curve:
        return 0.0
    days = (result.equity_curve[-1][0] - result.equity_curve[0][0]).days
    if days <= 0 or result.final_equity <= 0:
        return 0.0
    return (result.final_equity / result.initial_equity) ** (365.25 / days) - 1


def sharpe(result: BacktestResult) -> float:
    curve = [v for _, v in result.equity_curve]
    rets = [b / a - 1 for a, b in zip(curve, curve[1:]) if a > 0]
    if len(rets) < 2:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    if var == 0:
        return 0.0
    return mean / math.sqrt(var) * math.sqrt(252)


def summarize(result: BacktestResult) -> dict:
    wins = [t.pnl for t in result.trades if t.pnl > 0]
    losses = [t.pnl for t in result.trades if t.pnl <= 0]
    n = len(result.trades)
    return {
        "initial_equity": result.initial_equity,
        "final_equity": round(result.final_equity, 2),
        "total_return_pct": round(result.total_return * 100, 2),
        "cagr_pct": round(cagr(result) * 100, 2),
        "sharpe": round(sharpe(result), 2),
        "max_drawdown_pct": round(max_drawdown(result.equity_curve) * 100, 2),
        "trades": n,
        "win_rate_pct": round(100 * len(wins) / n, 1) if n else 0.0,
        "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "total_costs": round(sum(t.costs for t in result.trades), 2),
        "rejected_entries": result.rejected_entries,
        "final_state": result.final_state.value,
    }
