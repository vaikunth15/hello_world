"""Spec §3.2 — portfolio invariants: open-risk caps, groups, margin,
max contracts, no pyramiding."""

from goldguard.core.models import Side, SystemState, Verdict
from goldguard.risk.state import PortfolioState

from .conftest import GC, ZC, make_account, make_engine, make_intent, make_market, make_position


def evaluate(intent, *, account=None, portfolio=None, engine=None):
    return (engine or make_engine()).evaluate(
        intent, account or make_account(), portfolio or PortfolioState(), make_market()
    )


def test_no_pyramiding_same_direction():
    portfolio = PortfolioState(positions=[make_position(qty=1)])
    v = evaluate(make_intent(qty=1), portfolio=portfolio)
    assert v.verdict is Verdict.REJECTED
    assert any("pyramiding" in r for r in v.reasons)


def test_no_position_flip_via_entry():
    portfolio = PortfolioState(positions=[make_position(qty=1)])
    v = evaluate(make_intent(side=Side.SELL, qty=2), portfolio=portfolio)
    assert v.verdict is Verdict.REJECTED


def test_max_contracts_caps_qty():
    # $500k -> $2.5k budget -> 6 contracts by risk, but MGC max is 2.
    v = evaluate(make_intent(qty=6), account=make_account(equity=500_000, margin_capacity=500_000))
    assert v.verdict is Verdict.MODIFIED
    assert v.final_qty == 2


def test_portfolio_open_risk_cap_3pct():
    # Existing GC position risks $2700 (27 points x $100/pt x 1). New MGC trade
    # would exceed the $3000 (3%) cap unless reduced; headroom $300 < $400.
    gc_pos = make_position(instrument=GC, qty=1, avg_price=2000.0, stop_price=1973.0)
    engine = make_engine(correlation_groups={})  # isolate the portfolio cap from the group cap
    v = evaluate(make_intent(qty=1), portfolio=PortfolioState(positions=[gc_pos]), engine=engine)
    assert v.verdict is Verdict.REJECTED
    assert any("open-risk limit" in r for r in v.reasons)


def test_group_risk_cap_2pct_counts_correlated_as_one():
    # GC risk $1700 leaves group headroom $300 (<$400) although portfolio
    # headroom is $1300 — the correlated-group cap is the binding one.
    gc_pos = make_position(instrument=GC, qty=1, avg_price=2000.0, stop_price=1983.0)
    v = evaluate(make_intent(qty=1), portfolio=PortfolioState(positions=[gc_pos]))
    assert v.verdict is Verdict.REJECTED
    assert any("open-risk limit" in r for r in v.reasons)


def test_uncorrelated_instrument_only_hits_portfolio_cap():
    # Same $1700 of existing risk but in corn (different group): the 2% group
    # cap applies per group, so the MGC entry fits and is approved.
    zc_pos = make_position(instrument=ZC, qty=1, avg_price=450.0, stop_price=416.0)
    assert abs(zc_pos.open_risk - 1700.0) < 1e-6
    v = evaluate(make_intent(qty=1), portfolio=PortfolioState(positions=[zc_pos]))
    assert v.verdict is Verdict.APPROVED


def test_margin_cap_30pct():
    # Capacity $10k -> $3k margin headroom; 2 contracts need $2300, 3 need $3450.
    account = make_account(equity=200_000, margin_capacity=10_000)
    v = evaluate(make_intent(qty=2), account=account)
    assert v.allowed and v.final_qty == 2
    account_used = make_account(equity=200_000, margin_capacity=10_000, margin_used=2000)
    v = evaluate(make_intent(qty=2), account=account_used)
    assert v.verdict is Verdict.REJECTED  # headroom $1000 < $1150


def test_entries_blocked_in_every_non_running_state():
    for state in (SystemState.SOFT_HALT, SystemState.HARD_HALT, SystemState.FLATTENING, SystemState.FLAT_LOCKED):
        v = evaluate(make_intent(), account=make_account(state=state))
        assert v.verdict is Verdict.REJECTED, state


def test_disallowed_instrument_rejected():
    v = evaluate(make_intent(instrument=GC, qty=1))
    assert v.verdict is Verdict.REJECTED
    assert any("not allowed" in r for r in v.reasons)


def test_exit_allowed_even_when_halted():
    portfolio = PortfolioState(positions=[make_position(qty=2)])
    v = evaluate(
        make_intent(side=Side.SELL, qty=2, reduces_position=True),
        account=make_account(state=SystemState.HARD_HALT),
        portfolio=portfolio,
    )
    assert v.verdict is Verdict.APPROVED


def test_exit_capped_at_open_position():
    portfolio = PortfolioState(positions=[make_position(qty=1)])
    v = evaluate(make_intent(side=Side.SELL, qty=3, reduces_position=True), portfolio=portfolio)
    assert v.verdict is Verdict.MODIFIED
    assert v.final_qty == 1


def test_exit_wrong_side_rejected():
    portfolio = PortfolioState(positions=[make_position(qty=1)])
    v = evaluate(make_intent(side=Side.BUY, qty=1, reduces_position=True), portfolio=portfolio)
    assert v.verdict is Verdict.REJECTED


def test_exit_without_position_rejected():
    v = evaluate(make_intent(side=Side.SELL, qty=1, reduces_position=True))
    assert v.verdict is Verdict.REJECTED
