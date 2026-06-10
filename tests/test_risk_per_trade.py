"""Spec §3.1 — per-trade invariants, including boundary values."""

from goldguard.core.models import MGC, OrderIntent, OrderType, Side, Verdict

from .conftest import EMPTY_PORTFOLIO, make_account, make_engine, make_intent, make_market


def evaluate(intent, *, account=None, market=None, engine=None, portfolio=EMPTY_PORTFOLIO):
    return (engine or make_engine()).evaluate(intent, account or make_account(), portfolio, market or make_market())


def test_baseline_one_contract_approved():
    v = evaluate(make_intent(qty=1))
    assert v.verdict is Verdict.APPROVED
    assert v.final_qty == 1


def test_entry_without_stop_rejected():
    intent = OrderIntent(instrument=MGC, side=Side.BUY, qty=1, type=OrderType.LIMIT, limit_price=2000.0)
    v = evaluate(intent)
    assert v.verdict is Verdict.REJECTED
    assert any("stop" in r for r in v.reasons)


def test_stop_on_wrong_side_rejected():
    intent = OrderIntent(
        instrument=MGC, side=Side.BUY, qty=1, type=OrderType.LIMIT, limit_price=2000.0, stop_price=2040.0
    )
    v = evaluate(intent)
    assert v.verdict is Verdict.REJECTED
    assert any("losing side" in r for r in v.reasons)


def test_stop_band_boundaries():
    # 1.5x and 3.0x are inclusive; just outside is rejected. ATR 10 keeps the
    # risk budget non-binding so only the band is under test.
    market = make_market(atr=10.0)
    assert evaluate(make_intent(stop_atr_multiple=1.5, atr=10.0), market=market).allowed
    assert evaluate(make_intent(stop_atr_multiple=3.0, atr=10.0), market=market).allowed
    assert evaluate(make_intent(stop_atr_multiple=1.49, atr=10.0), market=market).verdict is Verdict.REJECTED
    assert evaluate(make_intent(stop_atr_multiple=3.01, atr=10.0), market=market).verdict is Verdict.REJECTED


def test_qty_below_one_contract_rejected():
    # $10k equity -> $50 budget vs $400/contract risk -> qty 0 -> reject.
    v = evaluate(make_intent(qty=1), account=make_account(equity=10_000))
    assert v.verdict is Verdict.REJECTED
    assert any("< 1 contract" in r for r in v.reasons)


def test_oversized_intent_is_modified_down():
    # $200k -> $1000 budget -> 2 contracts max.
    v = evaluate(make_intent(qty=5), account=make_account(equity=200_000))
    assert v.verdict is Verdict.MODIFIED
    assert v.final_qty == 2


def test_sizing_boundary_exact_budget():
    # Budget exactly equals risk of 1 contract: $400 risk needs $80k * 0.5%.
    v = evaluate(make_intent(qty=1), account=make_account(equity=80_000))
    assert v.verdict is Verdict.APPROVED
    v = evaluate(make_intent(qty=1), account=make_account(equity=79_999))
    assert v.verdict is Verdict.REJECTED


def test_deleverage_multiplier_halves_size():
    # $200k normally sizes 2; after deleverage x0.5 only 1.
    v = evaluate(make_intent(qty=2), account=make_account(equity=200_000, size_multiplier=0.5))
    assert v.verdict is Verdict.MODIFIED
    assert v.final_qty == 1


def test_short_entry_with_stop_above_approved():
    v = evaluate(make_intent(side=Side.SELL, qty=1))
    assert v.verdict is Verdict.APPROVED


def test_risk_per_trade_pct_cannot_exceed_one_percent():
    import pytest
    from goldguard.risk.config import RiskConfig

    with pytest.raises(ValueError):
        RiskConfig(risk_per_trade_pct=0.011)


def test_entry_without_limit_price_rejected():
    intent = OrderIntent(
        instrument=MGC, side=Side.BUY, qty=1, type=OrderType.MARKET, stop_price=1960.0
    )
    v = evaluate(intent)
    assert v.verdict is Verdict.REJECTED
    assert any("limit price" in r for r in v.reasons)
