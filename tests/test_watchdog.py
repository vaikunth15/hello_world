"""Phase 5 DoD: app death with an open position -> watchdog flattens within
90s and alerts. Plus watchdog behavior table and the 200-line audit budget."""

from pathlib import Path

from goldguard.core.heartbeat import Heartbeat
from goldguard.watchdog.watchdog import CHECK_INTERVAL_S, Watchdog


class Harness:
    def __init__(self, age, positions):
        self.age = age
        self.positions = positions
        self.flattened = 0
        self.alerts: list[str] = []
        self.watchdog = Watchdog(
            heartbeat_age_s=lambda: self.age,
            open_position_count=lambda: self.positions,
            flatten=self._flatten,
            alert=self.alerts.append,
        )

    def _flatten(self):
        self.flattened += 1
        self.positions = 0


def test_fresh_heartbeat_does_nothing():
    h = Harness(age=9.0, positions=3)
    assert h.watchdog.check_once() == "ok"
    assert h.flattened == 0 and not h.alerts


def test_dod_drill_dead_app_with_position_flattens_and_alerts():
    h = Harness(age=61.0, positions=2)  # main container killed >60s ago
    assert h.watchdog.check_once() == "flattened"
    assert h.flattened == 1
    assert h.alerts and "WATCHDOG FLATTENED 2" in h.alerts[0]
    # Reaction budget: staleness threshold + one check interval << 90s DoD.
    assert 60 + CHECK_INTERVAL_S <= 90


def test_no_heartbeat_ever_seen_counts_as_stale():
    h = Harness(age=None, positions=1)
    assert h.watchdog.check_once() == "flattened"
    assert h.flattened == 1


def test_stale_but_flat_alerts_without_flatten():
    h = Harness(age=120.0, positions=0)
    assert h.watchdog.check_once() == "stale-flat"
    assert h.flattened == 0
    assert h.alerts and "no open positions" in h.alerts[0]


def test_boundary_exactly_at_threshold_is_ok():
    h = Harness(age=60.0, positions=1)
    assert h.watchdog.check_once() == "ok"


def test_watchdog_stays_under_audit_budget():
    source = (Path(__file__).parent.parent / "goldguard" / "watchdog" / "watchdog.py").read_text()
    assert len(source.splitlines()) <= 200


def test_watchdog_shares_no_app_code():
    source = (Path(__file__).parent.parent / "goldguard" / "watchdog" / "watchdog.py").read_text()
    forbidden = ["goldguard.execution", "goldguard.risk", "goldguard.signals", "goldguard.api",
                 "goldguard.core", "goldguard.backtest", "goldguard.data"]
    for module in forbidden:
        assert module not in source, f"watchdog must not import {module}"


def test_heartbeat_writes_timestamp():
    written: dict[str, str] = {}
    hb = Heartbeat(write=lambda k, v: written.__setitem__(k, v))
    hb.beat()
    assert hb.beats == 1
    assert float(written["goldguard:heartbeat"]) > 0
