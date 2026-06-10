"""Spec §3.5 — property-based tests. For ANY random inputs:
- approved entries never push open risk past the portfolio/group caps,
- margin usage never passes 30%,
- size never increases after drawdown triggers,
- no order without a stop is ever allowed.
"""

from datetime import timedelta

from hypothesis import given, settings
from hypothesis import strategies as st

from goldguard.core.models import MGC, OrderIntent, OrderType, Position, Side, SystemState
from goldguard.risk.config import RiskConfig
from goldguard.risk.engine import RiskEngine
from goldguard.risk.ladder import DrawdownLadder
from goldguard.risk.state import PortfolioState

from .conftest import EMPTY_PORTFOLIO, GC, make_account, make_market, utc

ENGINE = RiskEngine(RiskConfig(allowed_instruments=["MGC", "GC"], max_contracts={"MGC": 2, "GC": 2}))
EPS = 1e-6


@st.composite
def positions(draw):
    inst = draw(st.sampled_from([MGC, GC]))
    qty = draw(st.integers(min_value=-2, max_value=2).filter(lambda q: q != 0))
    avg = draw(st.floats(min_value=1500, max_value=2500))
    distance = draw(st.floats(min_value=1.0, max_value=80.0))
    stop = avg - distance if qty > 0 else avg + distance
    return Position(instrument=inst, qty=qty, avg_price=avg, stop_price=stop, broker_stop_order_id="s")


@st.composite
def entry_intents(draw):
    side = draw(st.sampled_from([Side.BUY, Side.SELL]))
    entry = draw(st.floats(min_value=1500, max_value=2500))
    atr_multiple = draw(st.floats(min_value=1.0, max_value=3.5))
    atr = draw(st.floats(min_value=5.0, max_value=40.0))
    qty = draw(st.integers(min_value=1, max_value=10))
    stop = entry - atr_multiple * atr if side is Side.BUY else entry + atr_multiple * atr
    intent = OrderIntent(
        instrument=MGC, side=side, qty=qty, type=OrderType.LIMIT, limit_price=entry, stop_price=stop
    )
    return intent, atr


@settings(max_examples=300, deadline=None)
@given(
    portfolio_positions=st.lists(positions(), max_size=3),
    intent_atr=entry_intents(),
    equity=st.floats(min_value=10_000, max_value=2_000_000),
    margin_used=st.floats(min_value=0, max_value=50_000),
)
def test_caps_hold_for_any_approved_entry(portfolio_positions, intent_atr, equity, margin_used):
    intent, atr = intent_atr
    cfg = ENGINE._cfg
    # One position per instrument (mirrors reality; duplicates would be pyramiding).
    seen, dedup = set(), []
    for p in portfolio_positions:
        if p.instrument.symbol not in seen:
            seen.add(p.instrument.symbol)
            dedup.append(p)
    portfolio = PortfolioState(positions=dedup)
    account = make_account(equity=equity, margin_capacity=equity, margin_used=margin_used)

    verdict = ENGINE.evaluate(intent, account, portfolio, make_market(atr=atr))

    if verdict.allowed:
        q = verdict.final_qty
        assert 1 <= q <= intent.qty
        assert q <= cfg.max_contracts[intent.instrument.symbol]
        new_risk = abs(intent.entry_price - intent.stop_price) * MGC.point_value * q
        # Per-trade budget.
        assert new_risk <= equity * cfg.risk_per_trade_pct + EPS
        # Portfolio cap.
        assert portfolio.total_open_risk + new_risk <= cfg.portfolio_risk_cap_pct * equity + EPS
        # Correlated-group cap.
        group = cfg.group_of(intent.instrument.symbol)
        group_risk = sum(
            p.open_risk for p in dedup if cfg.group_of(p.instrument.symbol) == group
        )
        assert group_risk + new_risk <= cfg.group_risk_cap_pct * equity + EPS
        # Margin cap.
        assert margin_used + q * MGC.margin_estimate <= cfg.margin_cap_pct * equity + EPS
        # No pyramiding was possible.
        assert intent.instrument.symbol not in seen


@settings(max_examples=200, deadline=None)
@given(
    side=st.sampled_from([Side.BUY, Side.SELL]),
    qty=st.integers(min_value=1, max_value=10),
    entry=st.floats(min_value=1500, max_value=2500),
)
def test_no_order_without_stop_is_ever_allowed(side, qty, entry):
    intent = OrderIntent(
        instrument=MGC, side=side, qty=qty, type=OrderType.LIMIT, limit_price=entry, stop_price=None
    )
    verdict = ENGINE.evaluate(intent, make_account(), EMPTY_PORTFOLIO, make_market())
    assert not verdict.allowed


@settings(max_examples=200, deadline=None)
@given(
    pnl_steps=st.lists(st.floats(min_value=-0.06, max_value=0.06), min_size=1, max_size=40),
)
def test_size_multiplier_never_increases_under_any_price_path(pnl_steps):
    start = 100_000.0
    t = utc(2026, 1, 5, 12, 0)
    ladder = DrawdownLadder(hwm=start, day_start_equity=start, current_day=t.date())
    equity = start
    prev_multiplier = ladder.size_multiplier
    for i, step in enumerate(pnl_steps):
        equity = max(1.0, equity * (1 + step))
        now = t + timedelta(days=i)
        ladder.on_equity(equity, now)
        assert ladder.size_multiplier <= prev_multiplier
        prev_multiplier = ladder.size_multiplier
        drawdown = (ladder.hwm - equity) / ladder.hwm
        if drawdown >= 0.15:
            assert ladder.state in (SystemState.FLATTENING, SystemState.FLAT_LOCKED)
        if drawdown >= 0.10:
            assert ladder.size_multiplier == 0.5


@settings(max_examples=100, deadline=None)
@given(
    pnl_steps=st.lists(st.floats(min_value=-0.04, max_value=0.04), min_size=2, max_size=20),
)
def test_halt_severity_never_decreases_within_a_day(pnl_steps):
    from goldguard.risk.ladder import _SEVERITY

    start = 100_000.0
    t = utc(2026, 1, 5, 9, 0)
    ladder = DrawdownLadder(hwm=start, day_start_equity=start, current_day=t.date())
    equity = start
    prev = _SEVERITY[ladder.state]
    for i, step in enumerate(pnl_steps):
        equity = max(1.0, equity * (1 + step))
        ladder.on_equity(equity, t + timedelta(minutes=10 * i))  # same day throughout
        assert _SEVERITY[ladder.state] >= prev
        prev = _SEVERITY[ladder.state]
