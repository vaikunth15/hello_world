"""Timelocked risk-config governance (spec §3.5).

Rules enforced here:
- Any proposal is stored as a pending row with ``effective_at`` in the future.
- Tightening (every changed field moves in the stricter direction) takes
  effect immediately — emergency direction is asymmetric.
- Loosening any field delays the WHOLE proposal by at least 24 hours (the
  current config's ``timelock_hours``, whichever is larger).
- ``current(now)`` always returns the latest row whose ``effective_at`` has
  passed; pending rows are invisible to the engine until then.

The store is an interface; ``MemoryConfigStore`` backs tests and the
backtester, ``PostgresConfigStore`` (live deployment) persists the same rows.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from goldguard.core.models import Frozen
from goldguard.risk.config import MIN_TIMELOCK_HOURS, RiskConfig

# Direction of strictness per field: "down" means a lower value is stricter.
_STRICTER_DOWN = {
    "risk_per_trade_pct",
    "portfolio_risk_cap_pct",
    "group_risk_cap_pct",
    "margin_cap_pct",
    "stop_atr_max",
    "friday_entry_cutoff_hour_et",
}
_STRICTER_UP = {
    "stop_atr_min",
    "event_blackout_minutes",
    "session_open_blackout_minutes",
    "timelock_hours",
}


class ConfigRow(Frozen):
    config: RiskConfig
    created_at: datetime
    effective_at: datetime
    note: str = ""


def is_strictly_tightening(old: RiskConfig, new: RiskConfig) -> bool:
    """True only if every changed field moves in the stricter direction."""
    for field in RiskConfig.model_fields:
        ov, nv = getattr(old, field), getattr(new, field)
        if ov == nv:
            continue
        if field in _STRICTER_DOWN and nv < ov:
            continue
        if field in _STRICTER_UP and nv > ov:
            continue
        if field == "max_contracts":
            if set(nv) <= set(ov) and all(nv[k] <= ov[k] for k in nv):
                continue
            return False
        if field in ("allowed_instruments", "correlation_groups"):
            # Removing instruments / growing correlation groups is stricter.
            if field == "allowed_instruments" and set(nv) <= set(ov):
                continue
            if field == "correlation_groups" and all(
                set(ov.get(g, [])) <= set(nv.get(g, [])) for g in ov
            ):
                continue
            return False
        return False
    return True


class ConfigStore(Protocol):
    def rows(self) -> list[ConfigRow]: ...
    def append(self, row: ConfigRow) -> None: ...


class MemoryConfigStore:
    def __init__(self, initial: RiskConfig, at: datetime):
        self._rows: list[ConfigRow] = [ConfigRow(config=initial, created_at=at, effective_at=at)]

    def rows(self) -> list[ConfigRow]:
        return list(self._rows)

    def append(self, row: ConfigRow) -> None:
        self._rows.append(row)


class RiskGovernance:
    def __init__(self, store: ConfigStore):
        self._store = store

    def current(self, now: datetime) -> RiskConfig:
        effective = [r for r in self._store.rows() if r.effective_at <= now]
        if not effective:
            raise RuntimeError("no effective risk config — refuse to trade")
        # Stable sort: on equal effective_at (instant tightenings), the
        # later-appended row wins.
        return sorted(effective, key=lambda r: r.effective_at)[-1].config

    def pending(self, now: datetime) -> list[ConfigRow]:
        return [r for r in self._store.rows() if r.effective_at > now]

    def propose(self, new: RiskConfig, now: datetime, note: str = "") -> ConfigRow:
        current = self.current(now)
        if is_strictly_tightening(current, new):
            effective_at = now  # stricter is instant (spec §3.5)
        else:
            delay_h = max(MIN_TIMELOCK_HOURS, current.timelock_hours)
            effective_at = now + timedelta(hours=delay_h)
        row = ConfigRow(config=new, created_at=now, effective_at=effective_at, note=note)
        self._store.append(row)
        return row
