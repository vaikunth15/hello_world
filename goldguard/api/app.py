"""FastAPI control plane (spec §8).

Write surface is exactly: POST /halt, POST /flatten, POST /risk/config
(timelocked proposal). There is deliberately NO /resume that skips cooldown
and NO endpoint that weakens or disables the risk engine instantly — do not
add one (spec §0.2). Loosening goes through the 24h-timelocked proposal.

Auth: ``X-API-Key`` header. The control key may read and write; the
read-only dashboard key may only read.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field

from goldguard.core.config import Settings, load_settings
from goldguard.core.logging import configure_logging
from goldguard.api.system import TradingSystem


def _key(request: Request) -> str:
    return request.headers.get("X-API-Key", "")


def require_read(request: Request) -> None:
    settings: Settings = request.app.state.system.settings
    if _key(request) not in {settings.api_key, settings.readonly_key} or not _key(request):
        raise HTTPException(status_code=401, detail="invalid API key")


def require_control(request: Request) -> None:
    settings: Settings = request.app.state.system.settings
    if not settings.api_key or _key(request) != settings.api_key:
        raise HTTPException(status_code=401, detail="control API key required")


class HaltBody(BaseModel):
    reason: str = "manual halt"
    hard: bool = False


class FlattenBody(BaseModel):
    reason: str = "manual flatten"


class RiskConfigChange(BaseModel):
    """Only these fields may be proposed; anything else is rejected. There is
    no field that disables a check."""

    risk_per_trade_pct: float | None = Field(default=None, gt=0)
    portfolio_risk_cap_pct: float | None = Field(default=None, gt=0)
    group_risk_cap_pct: float | None = Field(default=None, gt=0)
    margin_cap_pct: float | None = Field(default=None, gt=0)
    max_contracts: dict[str, int] | None = None
    stop_atr_min: float | None = Field(default=None, gt=0)
    stop_atr_max: float | None = Field(default=None, gt=0)
    timelock_hours: int | None = None
    allowed_instruments: list[str] | None = None


def create_app(system: TradingSystem | None = None) -> FastAPI:
    configure_logging()
    app = FastAPI(title="GOLDGUARD control plane", version="0.1.0")
    app.state.system = system or TradingSystem(load_settings())

    def sys(request: Request) -> TradingSystem:
        return request.app.state.system

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/state", dependencies=[Depends(require_read)])
    def state(request: Request) -> dict:
        s = sys(request)
        return {
            "system_state": s.ladder.state.value,
            "mode": s.mode.value,
            "size_multiplier": s.ladder.size_multiplier,
            "instrument": s.settings.instrument.symbol,
        }

    @app.get("/positions", dependencies=[Depends(require_read)])
    def positions(request: Request) -> list[dict]:
        return [p.model_dump(mode="json") for p in sys(request).positions()]

    @app.get("/pnl", dependencies=[Depends(require_read)])
    def pnl(request: Request) -> dict:
        return sys(request).pnl()

    @app.get("/audit", dependencies=[Depends(require_read)])
    def audit(request: Request, since: datetime | None = Query(default=None)) -> list[dict]:
        if since is not None and since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        return [e.model_dump(mode="json") for e in sys(request).audit_since(since)]

    @app.get("/risk/config", dependencies=[Depends(require_read)])
    def risk_config(request: Request) -> dict:
        s = sys(request)
        now = datetime.now(timezone.utc)
        return {
            "effective": s.governance.current(now).model_dump(),
            "pending": [
                {"config": r.config.model_dump(), "effective_at": r.effective_at.isoformat(),
                 "note": r.note}
                for r in s.governance.pending(now)
            ],
        }

    @app.get("/slippage", dependencies=[Depends(require_read)])
    def slippage(request: Request) -> dict:
        return sys(request).slippage.stats()

    @app.post("/halt", dependencies=[Depends(require_control)])
    def halt(request: Request, body: HaltBody) -> dict:
        return {"system_state": sys(request).halt(body.reason, hard=body.hard).value}

    @app.post("/flatten", dependencies=[Depends(require_control)])
    def flatten(request: Request, body: FlattenBody) -> dict:
        return {"system_state": sys(request).flatten(body.reason).value}

    @app.post("/risk/config", dependencies=[Depends(require_control)])
    def propose_config(request: Request, body: RiskConfigChange) -> dict:
        changes = {k: v for k, v in body.model_dump().items() if v is not None}
        if not changes:
            raise HTTPException(status_code=422, detail="no changes proposed")
        try:
            row = sys(request).propose_risk_config(changes)
        except ValueError as exc:  # e.g. timelock below 24h, risk above 1%
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "status": "pending" if row.effective_at > datetime.now(timezone.utc) else "effective",
            "effective_at": row.effective_at.isoformat(),
        }

    return app
