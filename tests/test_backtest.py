"""Phase 3 — backtester invariants, metrics, walk-forward, report generation."""

from datetime import datetime, timezone

import pytest

from goldguard.backtest.costs import CostModel
from goldguard.backtest.engine import Backtester, BacktestResult
from goldguard.backtest.metrics import cagr, max_drawdown, sharpe, summarize
from goldguard.backtest.report import generate_report
from goldguard.backtest.walkforward import walk_forward
from goldguard.core.models import MGC, SystemState
from goldguard.data.synthetic import synthetic_gold_bars
from goldguard.risk.config import RiskConfig
from goldguard.signals.donchian import DonchianTrend
from goldguard.signals.ma_cross import MaCross

BARS = synthetic_gold_bars(n_days=900, seed=7)


@pytest.fixture(scope="module")
def result() -> BacktestResult:
    return Backtester(DonchianTrend(), RiskConfig(), CostModel()).run(BARS)


def test_backtest_is_deterministic(result):
    again = Backtester(DonchianTrend(), RiskConfig(), CostModel()).run(BARS)
    assert again == result


def test_backtest_produces_trades_and_curve(result):
    assert len(result.trades) > 5
    assert len(result.equity_curve) == len(BARS) - 60  # warmup excluded
    assert result.final_equity > 0


def test_no_position_ever_held_over_a_weekend(result):
    for t in result.trades:
        entry, exit_ = t.entry_time, t.exit_time
        assert exit_.isocalendar()[:2] == entry.isocalendar()[:2], (
            f"trade spans a weekend: {entry} -> {exit_} ({t.exit_reason})"
        )


def test_every_trade_costed(result):
    for t in result.trades:
        assert t.costs >= 2 * CostModel().commission_per_side * t.qty - 1e-9


def test_per_trade_loss_bounded_by_risk_budget(result):
    # 0.5% of equity + slippage on both legs + commissions, with headroom for
    # the equity high-water mark; gaps through stops are the only exception
    # and synthetic data keeps them small.
    peak = max(v for _, v in result.equity_curve)
    slip_buffer = 2 * 2 * MGC.tick_size * MGC.point_value  # 2 legs, up to 2 contracts
    bound = 0.005 * peak + slip_buffer + 4 * CostModel().commission_per_side
    for t in result.trades:
        if t.exit_reason == "stop":
            assert t.pnl >= -bound * 1.5, t


def test_drawdown_ladder_limits_curve_drawdown(result):
    # Hard halt flattens at 15% from HWM; allow same-day overshoot headroom.
    assert max_drawdown(result.equity_curve) <= 0.20


def test_ma_cross_also_runs():
    summary = summarize(Backtester(MaCross(), RiskConfig(), CostModel()).run(BARS))
    assert summary["trades"] >= 0 and summary["final_equity"] > 0


def test_metrics_math():
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    from datetime import timedelta

    curve = [(t0 + timedelta(days=i), v) for i, v in enumerate([100.0, 110.0, 99.0, 104.5])]
    assert max_drawdown(curve) == pytest.approx(0.1)
    flat = [(t0 + timedelta(days=i), 100.0) for i in range(10)]
    r = BacktestResult(
        equity_curve=flat, trades=[], initial_equity=100.0,
        rejected_entries=0, final_state=SystemState.RUNNING,
    )
    assert cagr(r) == 0.0 and sharpe(r) == 0.0


def test_cost_model_event_day_slippage():
    cm = CostModel(event_days=frozenset({BARS[0].timestamp.date()}))
    assert cm.slippage_points(MGC, BARS[0].timestamp.date()) == pytest.approx(0.4)
    assert cm.slippage_points(MGC, BARS[1].timestamp.date()) == pytest.approx(0.1)


def test_walk_forward_produces_oos_folds():
    bars = synthetic_gold_bars(n_days=1300, seed=11)
    wf = walk_forward(bars)
    # 1300 bars: folds start at 0 and 252 (756 train + 252 test each).
    assert wf["oos_years"] == 2
    fold = wf["folds"][0]
    assert fold["chosen_entry_window"] in (40, 55, 70)
    assert set(fold["train_scores"]) == {40, 55, 70}


def test_report_generation_flags_synthetic(tmp_path):
    out = tmp_path / "validation_report.md"
    text = generate_report(None, out)
    assert out.exists()
    assert "NOT VALID FOR THE PHASE GATE" in text
    assert "Parameter sensitivity" in text
    assert "Walk-forward" in text


def test_report_on_real_csv_is_not_flagged(tmp_path):
    bars_csv = tmp_path / "bars.csv"
    rows = ["timestamp,open,high,low,close,volume"]
    rows += [
        f"{b.timestamp.isoformat()},{b.open},{b.high},{b.low},{b.close},{b.volume}"
        for b in synthetic_gold_bars(n_days=1300, seed=3)
    ]
    bars_csv.write_text("\n".join(rows) + "\n")
    text = generate_report(bars_csv, tmp_path / "report.md")
    assert "NOT VALID" not in text
    assert "user-supplied" in text
