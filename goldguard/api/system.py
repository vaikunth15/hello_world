"""Composition root for the control plane: wires broker, drawdown ladder,
governance, audit log, and slippage stats into one object the API serves.
Paper mode uses the FakeBroker; live mode (triple-gated in core.config)
swaps in the IBKRAdapter behind the same protocol."""

from __future__ import annotations

from datetime import datetime, timezone

from goldguard.core.config import Settings, TradingMode
from goldguard.core.logging import get_logger
from goldguard.core.models import AuditEvent, Position, SystemState
from goldguard.execution.broker import BrokerAdapter, FakeBroker
from goldguard.execution.slippage import SlippageTracker
from goldguard.risk.config import RiskConfig
from goldguard.risk.governance import ConfigRow, MemoryConfigStore, RiskGovernance
from goldguard.risk.ladder import DrawdownLadder

log = get_logger("system")


class TradingSystem:
    def __init__(self, settings: Settings, broker: BrokerAdapter | None = None,
                 now: datetime | None = None):
        now = now or datetime.now(timezone.utc)
        self.settings = settings
        self.mode, mode_reasons = settings.resolve_mode()
        if self.mode is TradingMode.PAPER:
            log.info("running in PAPER mode", unmet_live_requirements=mode_reasons)
        self.broker: BrokerAdapter = broker or FakeBroker()
        equity = self.broker.account().equity
        self.ladder = DrawdownLadder(hwm=equity, day_start_equity=equity, current_day=now.date())
        self.governance = RiskGovernance(MemoryConfigStore(RiskConfig(), now))
        self.audit: list[AuditEvent] = []
        self.slippage = SlippageTracker(
            modeled_cost_per_trade=2 * 1.24 + 2 * settings.instrument.tick_value,
            halt=self._halt_fn, alert=self._alert,
        )

    # -- safety actions ---------------------------------------------------

    def _alert(self, message: str) -> None:
        log.critical(message)
        self.record("alert", {"message": message})

    def _halt_fn(self, reason: str, hard: bool) -> None:
        self.halt(reason, hard=hard)

    def halt(self, reason: str, hard: bool = False) -> SystemState:
        self.ladder.operational_halt(datetime.now(timezone.utc), reason, hard=hard)
        self.record("state_transition", {"action": "halt", "hard": hard, "reason": reason})
        return self.ladder.state

    def flatten(self, reason: str) -> SystemState:
        self.broker.flatten_all()
        now = datetime.now(timezone.utc)
        self.ladder.operational_halt(now, reason, hard=True)
        self.ladder.on_flattened(now)
        self.record("state_transition", {"action": "flatten", "reason": reason})
        return self.ladder.state

    # -- read models --------------------------------------------------------

    def positions(self) -> list[Position]:
        return self.broker.positions()

    def pnl(self) -> dict:
        account = self.broker.account()
        return {
            "equity": account.equity,
            "day_start_equity": self.ladder.day_start_equity,
            "daily_pnl": account.equity - self.ladder.day_start_equity,
            "high_water_mark": self.ladder.hwm,
            "drawdown_pct": round(100 * (self.ladder.hwm - account.equity) / self.ladder.hwm, 3),
            "size_multiplier": self.ladder.size_multiplier,
            "margin_used": account.margin_used,
        }

    def audit_since(self, since: datetime | None) -> list[AuditEvent]:
        events = sorted(self.audit + self.ladder.events, key=lambda e: e.timestamp)
        if since is not None:
            events = [e for e in events if e.timestamp >= since]
        return events

    def record(self, kind: str, payload: dict) -> None:
        self.audit.append(AuditEvent(timestamp=datetime.now(timezone.utc), kind=kind, payload=payload))

    # -- governance -----------------------------------------------------------

    def propose_risk_config(self, changes: dict) -> ConfigRow:
        now = datetime.now(timezone.utc)
        current = self.governance.current(now)
        new = current.model_copy(update=changes)
        row = self.governance.propose(RiskConfig(**new.model_dump()), now,
                                      note=f"api change: {sorted(changes)}")
        self.record("config", {"changes": changes, "effective_at": row.effective_at.isoformat()})
        return row
