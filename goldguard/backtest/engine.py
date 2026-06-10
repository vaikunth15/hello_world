"""Event-driven backtester (spec §7).

Replays daily bars through the SAME code paths as live trading:
- the strategy's pure ``generate`` (desired direction after each close),
- the real ``RiskEngine.evaluate`` with real ``AccountState``/``MarketState``,
- the real ``DrawdownLadder``,
- a broker simulation that mirrors what the OrderManager + broker do:
  next-open fills with slippage and commission, a broker-side stop checked
  intrabar every day, and the Friday-16:00-ET weekend flatten.

Nothing here re-implements a risk rule; if the engine would reject it live,
it is rejected here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from goldguard.backtest.costs import CostModel
from goldguard.core.models import (
    Bar,
    Direction,
    Frozen,
    Instrument,
    MGC,
    OrderIntent,
    OrderType,
    Side,
    SystemState,
)

# Ask the risk engine for "as much as my rules allow": it caps the request at
# the per-trade budget, max-contracts, portfolio and margin limits.
ASK_MAX_QTY = 10_000
from goldguard.data.macro import MacroState
from goldguard.risk.config import RiskConfig
from goldguard.risk.engine import RiskEngine
from goldguard.risk.ladder import DrawdownLadder
from goldguard.risk.state import AccountState, MarketState, PortfolioState
from goldguard.signals.base import Strategy
from goldguard.signals.indicators import atr

ET = ZoneInfo("America/New_York")
WARMUP_BARS = 60


class Trade(Frozen):
    direction: Direction
    qty: int
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    pnl: float  # net of costs
    costs: float
    exit_reason: str  # stop | signal | weekend_flatten | end_of_data | risk_flatten


class BacktestResult(Frozen):
    equity_curve: list[tuple[datetime, float]]
    trades: list[Trade]
    initial_equity: float
    rejected_entries: int
    final_state: SystemState

    @property
    def final_equity(self) -> float:
        return self.equity_curve[-1][1] if self.equity_curve else self.initial_equity

    @property
    def total_return(self) -> float:
        return self.final_equity / self.initial_equity - 1


@dataclass
class _OpenPosition:
    direction: Direction
    qty: int
    entry_price: float
    entry_time: datetime
    stop_price: float
    costs_paid: float


class Backtester:
    def __init__(
        self,
        strategy: Strategy,
        risk_config: RiskConfig | None = None,
        costs: CostModel | None = None,
        instrument: Instrument = MGC,
        initial_equity: float = 100_000.0,
        macro_for: "callable | None" = None,  # date -> MacroState; default: always favorable
    ):
        self._strategy = strategy
        self._engine = RiskEngine(risk_config or RiskConfig())
        self._costs = costs or CostModel()
        self._inst = instrument
        self._initial_equity = initial_equity
        self._macro_for = macro_for or (
            lambda _d: MacroState(real_yield_20d_change=-0.1, dxy=100.0, dxy_50d_ma=101.0)
        )

    def run(self, bars: list[Bar]) -> BacktestResult:
        inst = self._inst
        equity = self._initial_equity
        ladder = DrawdownLadder(
            hwm=equity, day_start_equity=equity, current_day=bars[0].timestamp.date()
        )
        pos: _OpenPosition | None = None
        pending: tuple[OrderIntent, float] | None = None  # (approved intent, stop_distance)
        trades: list[Trade] = []
        curve: list[tuple[datetime, float]] = []
        rejected = 0

        def close_position(p: _OpenPosition, t: datetime, price: float, reason: str) -> float:
            slip = self._costs.slippage_points(inst, t.date())
            fill = price - slip if p.direction is Direction.LONG else price + slip
            gross = (
                (fill - p.entry_price) if p.direction is Direction.LONG else (p.entry_price - fill)
            ) * p.qty * inst.point_value
            cost = self._costs.commission(p.qty) + p.costs_paid
            trades.append(
                Trade(
                    direction=p.direction, qty=p.qty, entry_time=p.entry_time,
                    entry_price=p.entry_price, exit_time=t, exit_price=fill,
                    pnl=gross - cost, costs=cost, exit_reason=reason,
                )
            )
            return gross - self._costs.commission(p.qty)

        for i in range(WARMUP_BARS, len(bars)):
            bar = bars[i]
            day = bar.timestamp.date()

            # 1. Fill yesterday's approved entry at today's open (+slippage).
            if pending is not None and pos is None and ladder.state is SystemState.RUNNING:
                intent, _ = pending
                slip = self._costs.slippage_points(inst, day)
                fill = bar.open + slip if intent.side is Side.BUY else bar.open - slip
                direction = Direction.LONG if intent.side is Side.BUY else Direction.SHORT
                stop_offset = abs(intent.entry_price - intent.stop_price)
                stop = fill - stop_offset if direction is Direction.LONG else fill + stop_offset
                pos = _OpenPosition(
                    direction=direction, qty=intent.qty, entry_price=fill,
                    entry_time=bar.timestamp, stop_price=stop,
                    costs_paid=self._costs.commission(intent.qty),
                )
            pending = None

            # 2. Broker-side stop, checked intrabar.
            if pos is not None:
                stopped = (
                    bar.low <= pos.stop_price if pos.direction is Direction.LONG
                    else bar.high >= pos.stop_price
                )
                if stopped:
                    equity += close_position(pos, bar.timestamp, pos.stop_price, "stop")
                    pos = None

            # 3. Mark to market, feed the drawdown ladder (same ladder as live).
            mtm = equity
            if pos is not None:
                unreal = (
                    (bar.close - pos.entry_price) if pos.direction is Direction.LONG
                    else (pos.entry_price - bar.close)
                ) * pos.qty * inst.point_value
                mtm += unreal
            state = ladder.on_equity(mtm, bar.timestamp)
            if state in (SystemState.FLATTENING, SystemState.HARD_HALT) and pos is not None:
                equity += close_position(pos, bar.timestamp, bar.close, "risk_flatten")
                pos = None
                ladder.on_flattened(bar.timestamp)
                mtm = equity
            curve.append((bar.timestamp, mtm))

            # 4. Post-close evaluation: desired direction from the pure strategy.
            signal = self._strategy.generate(bars[: i + 1], self._macro_for(day))
            desired = signal.direction

            # 5. Exit on signal change (exits are always allowed).
            if pos is not None and desired is not pos.direction:
                equity += close_position(pos, bar.timestamp, bar.close, "signal")
                pos = None

            # 6. Weekend flatten: nothing held past Friday 16:00 ET (spec §3.3).
            if pos is not None and bar.timestamp.astimezone(ET).weekday() == 4:
                equity += close_position(pos, bar.timestamp, bar.close, "weekend_flatten")
                pos = None

            # 7. New entry intent through the real risk engine.
            if pos is None and desired in (Direction.LONG, Direction.SHORT) and i + 1 < len(bars):
                daily_atr = atr(bars[max(0, i - 100) : i + 1], 14)
                entry_ref = bar.close
                stop_distance = signal.proposed_stop_atr_multiple * daily_atr
                side = Side.BUY if desired is Direction.LONG else Side.SELL
                stop_price = entry_ref - stop_distance if side is Side.BUY else entry_ref + stop_distance
                intent = OrderIntent(
                    instrument=inst, side=side, qty=ASK_MAX_QTY, type=OrderType.LIMIT,
                    limit_price=entry_ref, stop_price=stop_price, parent_signal_id=signal.strategy_id,
                )
                account = AccountState(
                    equity=mtm, margin_capacity=mtm, margin_used=0.0,
                    system_state=ladder.state, size_multiplier=ladder.size_multiplier,
                )
                portfolio = PortfolioState(positions=[])
                market = MarketState(now=bar.timestamp, atr_14=daily_atr)
                verdict = self._engine.evaluate(intent, account, portfolio, market)
                if verdict.allowed:
                    pending = (
                        intent.model_copy(update={"qty": verdict.final_qty}),
                        stop_distance,
                    )
                else:
                    rejected += 1

        if pos is not None:
            last = bars[-1]
            equity += close_position(pos, last.timestamp, last.close, "end_of_data")
            curve[-1] = (last.timestamp, equity)

        return BacktestResult(
            equity_curve=curve, trades=trades, initial_equity=self._initial_equity,
            rejected_entries=rejected, final_state=ladder.state,
        )
