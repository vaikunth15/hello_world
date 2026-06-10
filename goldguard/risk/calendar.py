"""Economic calendar (spec §3.3). Seeded from a JSON config file:

    [{"name": "FOMC", "timestamp": "2026-06-17T14:00:00-04:00", "impact": "high"}, ...]

The scheduler loads this once a day and passes the relevant slice to the
risk engine via ``MarketState.upcoming_events``.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from goldguard.risk.state import EconomicEvent


def load_calendar(path: Path) -> list[EconomicEvent]:
    raw = json.loads(path.read_text())
    events = [EconomicEvent(**e) for e in raw]
    if any(e.timestamp.tzinfo is None for e in events):
        raise ValueError("calendar timestamps must be timezone-aware")
    return sorted(events, key=lambda e: e.timestamp)


def events_within(events: list[EconomicEvent], now: datetime, horizon: timedelta) -> list[EconomicEvent]:
    return [e for e in events if now <= e.timestamp <= now + horizon and e.impact == "high"]
