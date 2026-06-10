"""Application configuration.

Invariants enforced here (spec §0):
- Paper trading is the default mode. ``mode`` can only become LIVE when
  ``GOLDGUARD_LIVE=true`` is set in the environment AND the config carries a
  valid HMAC signature over the live-relevant fields AND the Phase Gate
  checklist file exists with every box checked. Failing any one of the three
  silently degrades to PAPER and logs why.
- The default instrument is MGC. Switching instruments is a risk-config
  change and therefore timelocked (see ``goldguard.risk.governance``).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class TradingMode(StrEnum):
    PAPER = "paper"
    LIVE = "live"


class InstrumentSpec(BaseModel):
    symbol: str = "MGC"
    exchange: str = "COMEX"
    tick_size: float = 0.1
    tick_value: float = 1.0
    multiplier: int = 10
    margin_estimate: float = 1150.0


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GOLDGUARD_", env_file=".env", extra="ignore")

    mode: TradingMode = TradingMode.PAPER
    live: bool = False  # GOLDGUARD_LIVE env var; necessary but not sufficient
    live_signature: str = ""  # HMAC over live fields, signed with signing_key
    signing_key: str = ""
    phase_gate_checklist: Path = Path("docs/PHASE_GATE.md")

    db_dsn: str = "postgresql://goldguard:goldguard@localhost:5432/goldguard"
    redis_url: str = "redis://localhost:6379/0"
    api_key: str = ""
    readonly_key: str = ""
    fred_api_key: str = ""

    account_id: str = "PAPER000"
    instrument: InstrumentSpec = InstrumentSpec()
    strategy: str = "donchian"  # or "ma_cross"; one at a time (spec §4)

    heartbeat_interval_s: int = 10
    watchdog_stale_after_s: int = 60
    alert_webhook_url: str = ""

    def live_payload(self) -> bytes:
        """The byte string that ``live_signature`` must sign."""
        return f"{self.account_id}|{self.instrument.symbol}|live".encode()

    def resolve_mode(self) -> tuple[TradingMode, list[str]]:
        """Resolve the effective trading mode.

        Returns (mode, reasons). Reasons explain every unmet live
        requirement; the list is empty only when LIVE is granted.
        """
        reasons: list[str] = []
        if self.mode is not TradingMode.LIVE:
            reasons.append("mode is not 'live'")
        if not self.live or os.environ.get("GOLDGUARD_LIVE", "").lower() != "true":
            reasons.append("GOLDGUARD_LIVE=true not set in environment")
        if not self._signature_valid():
            reasons.append("live_signature missing or invalid")
        if not self._phase_gate_complete():
            reasons.append(f"phase gate checklist incomplete: {self.phase_gate_checklist}")
        if reasons:
            return TradingMode.PAPER, reasons
        return TradingMode.LIVE, []

    def _signature_valid(self) -> bool:
        if not self.signing_key or not self.live_signature:
            return False
        expected = hmac.new(self.signing_key.encode(), self.live_payload(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, self.live_signature)

    def _phase_gate_complete(self) -> bool:
        try:
            text = self.phase_gate_checklist.read_text()
        except OSError:
            return False
        boxes = re.findall(r"- \[(x| )\]", text)
        return bool(boxes) and all(b == "x" for b in boxes)


def load_settings(**overrides) -> Settings:
    return Settings(**overrides)
