"""Risk parameters (spec §3). Every field here is governed by the timelock in
``goldguard.risk.governance`` — the engine only ever reads the currently
effective row, never a proposal.
"""

from __future__ import annotations

from pydantic import Field, field_validator

from goldguard.core.models import Frozen

MIN_TIMELOCK_HOURS = 24
MAX_RISK_PER_TRADE_PCT = 0.01


class RiskConfig(Frozen):
    risk_per_trade_pct: float = Field(default=0.005, gt=0, le=MAX_RISK_PER_TRADE_PCT)
    portfolio_risk_cap_pct: float = Field(default=0.03, gt=0)
    group_risk_cap_pct: float = Field(default=0.02, gt=0)
    margin_cap_pct: float = Field(default=0.30, gt=0, le=1.0)
    max_contracts: dict[str, int] = {"MGC": 2}
    stop_atr_min: float = Field(default=1.5, gt=0)
    stop_atr_max: float = Field(default=3.0, gt=0)
    event_blackout_minutes: int = Field(default=30, ge=0)
    session_open_blackout_minutes: int = Field(default=5, ge=0)
    friday_entry_cutoff_hour_et: int = Field(default=14, ge=0, le=23)
    timelock_hours: int = Field(default=MIN_TIMELOCK_HOURS)
    allowed_instruments: list[str] = ["MGC"]
    correlation_groups: dict[str, list[str]] = {
        "precious_metals": ["MGC", "GC", "SIL", "SI", "GDX", "HG", "MHG"],
    }

    @field_validator("timelock_hours")
    @classmethod
    def _timelock_floor(cls, v: int) -> int:
        if v < MIN_TIMELOCK_HOURS:
            raise ValueError(f"timelock_hours may never be below {MIN_TIMELOCK_HOURS} (spec §0.3)")
        return v

    def group_of(self, symbol: str) -> str:
        for group, members in self.correlation_groups.items():
            if symbol in members:
                return group
        return f"__solo__{symbol}"
