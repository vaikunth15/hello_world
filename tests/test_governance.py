"""Spec §3.5 — timelocked governance. The DoD requires proving a config
change is inactive before 24h."""

from datetime import timedelta

import pytest

from goldguard.risk.config import RiskConfig
from goldguard.risk.governance import MemoryConfigStore, RiskGovernance, is_strictly_tightening

from .conftest import utc

T0 = utc(2026, 6, 1, 12, 0)


def make_gov(initial: RiskConfig | None = None) -> RiskGovernance:
    return RiskGovernance(MemoryConfigStore(initial or RiskConfig(), T0))


def test_loosening_is_inactive_before_24h_and_active_after():
    gov = make_gov()
    looser = RiskConfig(risk_per_trade_pct=0.008)
    row = gov.propose(looser, T0, note="raise risk")
    assert row.effective_at == T0 + timedelta(hours=24)

    assert gov.current(T0).risk_per_trade_pct == 0.005
    assert gov.current(T0 + timedelta(hours=23, minutes=59)).risk_per_trade_pct == 0.005
    assert gov.current(T0 + timedelta(hours=24)).risk_per_trade_pct == 0.008
    assert gov.pending(T0) == [row]


def test_tightening_is_instant():
    gov = make_gov()
    stricter = RiskConfig(risk_per_trade_pct=0.003, margin_cap_pct=0.20)
    gov.propose(stricter, T0)
    assert gov.current(T0).risk_per_trade_pct == 0.003


def test_mixed_change_is_fully_timelocked():
    # One stricter field + one looser field -> the WHOLE proposal waits.
    gov = make_gov()
    mixed = RiskConfig(risk_per_trade_pct=0.003, portfolio_risk_cap_pct=0.05)
    gov.propose(mixed, T0)
    assert gov.current(T0 + timedelta(hours=1)).portfolio_risk_cap_pct == 0.03


def test_longer_timelock_extends_delay_for_loosening():
    gov = make_gov(RiskConfig(timelock_hours=48))
    row = gov.propose(RiskConfig(timelock_hours=48, risk_per_trade_pct=0.008), T0)
    assert row.effective_at == T0 + timedelta(hours=48)


def test_timelock_can_rise_instantly_but_never_below_24h():
    gov = make_gov()
    gov.propose(RiskConfig(timelock_hours=72), T0)
    assert gov.current(T0).timelock_hours == 72  # raising = stricter = instant
    with pytest.raises(ValueError):
        RiskConfig(timelock_hours=23)


def test_adding_instrument_is_timelocked():
    gov = make_gov()
    row = gov.propose(RiskConfig(allowed_instruments=["MGC", "GC"]), T0)
    assert row.effective_at > T0
    assert gov.current(T0).allowed_instruments == ["MGC"]


def test_removing_instrument_is_instant():
    gov = make_gov(RiskConfig(allowed_instruments=["MGC", "GC"]))
    gov.propose(RiskConfig(allowed_instruments=["MGC"]), T0)
    assert gov.current(T0).allowed_instruments == ["MGC"]


def test_max_contracts_direction():
    assert is_strictly_tightening(RiskConfig(), RiskConfig(max_contracts={"MGC": 1}))
    assert not is_strictly_tightening(RiskConfig(), RiskConfig(max_contracts={"MGC": 3}))
    # Adding a new instrument's cap is a loosening (it enables trading it).
    assert not is_strictly_tightening(RiskConfig(), RiskConfig(max_contracts={"MGC": 2, "GC": 1}))


def test_correlation_group_direction():
    grown = RiskConfig(correlation_groups={"precious_metals": RiskConfig().correlation_groups["precious_metals"] + ["PL"]})
    assert is_strictly_tightening(RiskConfig(), grown)  # bigger group = stricter
    shrunk = RiskConfig(correlation_groups={"precious_metals": ["MGC"]})
    assert not is_strictly_tightening(RiskConfig(), shrunk)


def test_stop_band_direction():
    assert is_strictly_tightening(RiskConfig(), RiskConfig(stop_atr_min=2.0))
    assert not is_strictly_tightening(RiskConfig(), RiskConfig(stop_atr_min=1.0))
    assert is_strictly_tightening(RiskConfig(), RiskConfig(stop_atr_max=2.5))
    assert not is_strictly_tightening(RiskConfig(), RiskConfig(stop_atr_max=3.5))


def test_no_effective_config_refuses():
    gov = make_gov()
    with pytest.raises(RuntimeError):
        gov.current(T0 - timedelta(days=1))


def test_engine_reads_only_effective_row():
    from goldguard.risk.engine import RiskEngine

    from .conftest import EMPTY_PORTFOLIO, make_account, make_intent, make_market

    gov = make_gov()
    gov.propose(RiskConfig(risk_per_trade_pct=0.01), T0)  # looser, pending

    # At T0 the effective config is still 0.5%: $100k sizes 1 contract, not 2.
    engine = RiskEngine(gov.current(T0))
    v = engine.evaluate(make_intent(qty=2), make_account(), EMPTY_PORTFOLIO, make_market())
    assert v.final_qty == 1
