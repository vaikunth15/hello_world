"""Spec §3.3 — time-based invariants, with boundary values."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from goldguard.core.models import Verdict
from goldguard.risk.state import EconomicEvent

from .conftest import EMPTY_PORTFOLIO, SAFE_NOW, make_account, make_engine, make_intent, make_market

ET = ZoneInfo("America/New_York")


def evaluate(market):
    return make_engine().evaluate(make_intent(), make_account(), EMPTY_PORTFOLIO, market)


def test_friday_cutoff_boundary():
    friday_1359 = datetime(2026, 6, 12, 13, 59, tzinfo=ET)
    friday_1400 = datetime(2026, 6, 12, 14, 0, tzinfo=ET)
    assert evaluate(make_market(now=friday_1359)).allowed
    v = evaluate(make_market(now=friday_1400))
    assert v.verdict is Verdict.REJECTED
    assert any("Friday" in r for r in v.reasons)


def test_friday_cutoff_uses_eastern_time():
    # 18:30 UTC on a Friday is 14:30 ET — must be rejected even in UTC terms.
    from datetime import timezone

    friday_utc = datetime(2026, 6, 12, 18, 30, tzinfo=timezone.utc)
    assert evaluate(make_market(now=friday_utc)).verdict is Verdict.REJECTED


def test_saturday_rejected():
    saturday = datetime(2026, 6, 13, 10, 0, tzinfo=ET)
    assert evaluate(make_market(now=saturday)).verdict is Verdict.REJECTED


def test_event_blackout_window():
    fomc = EconomicEvent(name="FOMC", timestamp=SAFE_NOW + timedelta(minutes=29))
    v = evaluate(make_market(upcoming_events=[fomc]))
    assert v.verdict is Verdict.REJECTED
    assert any("FOMC" in r for r in v.reasons)


def test_event_blackout_boundaries():
    at_30 = EconomicEvent(name="CPI", timestamp=SAFE_NOW + timedelta(minutes=30))
    at_31 = EconomicEvent(name="CPI", timestamp=SAFE_NOW + timedelta(minutes=31))
    past = EconomicEvent(name="CPI", timestamp=SAFE_NOW - timedelta(minutes=1))
    assert evaluate(make_market(upcoming_events=[at_30])).verdict is Verdict.REJECTED
    assert evaluate(make_market(upcoming_events=[at_31])).allowed
    assert evaluate(make_market(upcoming_events=[past])).allowed


def test_session_open_blackout():
    open_t = SAFE_NOW - timedelta(minutes=4)
    v = evaluate(make_market(session_open=open_t))
    assert v.verdict is Verdict.REJECTED
    assert any("session" in r for r in v.reasons)
    assert evaluate(make_market(session_open=SAFE_NOW - timedelta(minutes=5))).allowed


def test_calendar_loading(tmp_path):
    from goldguard.risk.calendar import events_within, load_calendar

    p = tmp_path / "calendar.json"
    p.write_text(
        '[{"name": "NFP", "timestamp": "2026-07-02T08:30:00-04:00"},'
        ' {"name": "minor", "timestamp": "2026-07-01T08:30:00-04:00", "impact": "low"}]'
    )
    events = load_calendar(p)
    assert [e.name for e in events] == ["minor", "NFP"]
    near = events_within(events, datetime(2026, 7, 2, 8, 15, tzinfo=ET), timedelta(hours=1))
    assert [e.name for e in near] == ["NFP"]


def test_calendar_rejects_naive_timestamps(tmp_path):
    import pytest

    from goldguard.risk.calendar import load_calendar

    p = tmp_path / "calendar.json"
    p.write_text('[{"name": "NFP", "timestamp": "2026-07-02T08:30:00"}]')
    with pytest.raises(ValueError):
        load_calendar(p)
