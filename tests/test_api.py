"""Phase 6 — control plane API: auth split, instant halt/flatten, timelocked
config proposals, and the absence of any bypass endpoint."""

import pytest
from fastapi.testclient import TestClient

from goldguard.api.app import create_app
from goldguard.api.system import TradingSystem
from goldguard.core.config import Settings
from goldguard.core.models import RiskVerdict, Verdict
from goldguard.execution.broker import FakeBroker
from goldguard.execution.order_manager import MemoryOrderStore, OrderManager

from .conftest import make_intent, utc

CONTROL = {"X-API-Key": "control-key"}
READONLY = {"X-API-Key": "readonly-key"}


@pytest.fixture()
def system() -> TradingSystem:
    settings = Settings(_env_file=None, api_key="control-key", readonly_key="readonly-key")
    return TradingSystem(settings, broker=FakeBroker())


@pytest.fixture()
def client(system) -> TestClient:
    return TestClient(create_app(system))


def open_position(system: TradingSystem) -> None:
    manager = OrderManager(system.broker, MemoryOrderStore(), system._halt_fn)
    result = manager.execute(
        make_intent(qty=1), RiskVerdict(verdict=Verdict.APPROVED, final_qty=1), utc(2026, 6, 9, 15, 0)
    )
    assert result.sent


def test_health_is_public(client):
    assert client.get("/health").status_code == 200


def test_reads_require_a_key(client):
    for path in ("/state", "/positions", "/pnl", "/audit", "/risk/config", "/slippage"):
        assert client.get(path).status_code == 401, path
        assert client.get(path, headers={"X-API-Key": "wrong"}).status_code == 401, path
        assert client.get(path, headers=READONLY).status_code == 200, path


def test_readonly_key_cannot_write(client):
    assert client.post("/halt", json={}, headers=READONLY).status_code == 401
    assert client.post("/flatten", json={}, headers=READONLY).status_code == 401
    assert client.post("/risk/config", json={"risk_per_trade_pct": 0.004}, headers=READONLY).status_code == 401


def test_empty_configured_keys_never_match():
    system = TradingSystem(Settings(_env_file=None, api_key="", readonly_key=""))
    client = TestClient(create_app(system))
    assert client.get("/state", headers={"X-API-Key": ""}).status_code == 401
    assert client.post("/halt", json={}, headers={"X-API-Key": ""}).status_code == 401


def test_state_and_pnl_shape(client):
    state = client.get("/state", headers=READONLY).json()
    assert state["system_state"] == "RUNNING" and state["mode"] == "paper"
    pnl = client.get("/pnl", headers=READONLY).json()
    assert pnl["equity"] == 100_000.0 and pnl["daily_pnl"] == 0.0


def test_halt_is_instant_and_audited(client):
    r = client.post("/halt", json={"reason": "ops drill"}, headers=CONTROL)
    assert r.json()["system_state"] == "SOFT_HALT"
    audit = client.get("/audit", headers=READONLY).json()
    assert any(e["payload"].get("action") == "halt" for e in audit)


def test_flatten_closes_positions_and_hard_halts(client, system):
    open_position(system)
    assert client.get("/positions", headers=READONLY).json() != []
    r = client.post("/flatten", json={"reason": "ops drill"}, headers=CONTROL)
    assert r.json()["system_state"] == "FLAT_LOCKED"
    assert client.get("/positions", headers=READONLY).json() == []


def test_risk_config_loosening_is_pending_not_effective(client):
    r = client.post("/risk/config", json={"risk_per_trade_pct": 0.008}, headers=CONTROL)
    assert r.status_code == 200
    assert r.json()["status"] == "pending"
    cfg = client.get("/risk/config", headers=READONLY).json()
    assert cfg["effective"]["risk_per_trade_pct"] == 0.005
    assert len(cfg["pending"]) == 1


def test_risk_config_tightening_is_instant(client):
    r = client.post("/risk/config", json={"risk_per_trade_pct": 0.003}, headers=CONTROL)
    assert r.json()["status"] == "effective"
    cfg = client.get("/risk/config", headers=READONLY).json()
    assert cfg["effective"]["risk_per_trade_pct"] == 0.003


def test_risk_config_hard_ceilings_enforced(client):
    assert client.post("/risk/config", json={"risk_per_trade_pct": 0.02}, headers=CONTROL).status_code == 422
    assert client.post("/risk/config", json={"timelock_hours": 12}, headers=CONTROL).status_code == 422
    assert client.post("/risk/config", json={}, headers=CONTROL).status_code == 422


def test_no_resume_or_bypass_endpoints_exist(client):
    # Spec §0.2/§8: these must not exist. 404/405 proves the route is absent.
    for path in ("/resume", "/risk/disable", "/risk/bypass", "/force", "/unhalt"):
        assert client.post(path, json={}, headers=CONTROL).status_code in (404, 405), path
    # And the config surface has no enable/disable switch.
    fields = client.get("/risk/config", headers=READONLY).json()["effective"].keys()
    assert not any("enable" in f or "bypass" in f or "force" in f for f in fields)


def test_audit_since_filter(client):
    client.post("/halt", json={"reason": "first"}, headers=CONTROL)
    events = client.get("/audit", headers=READONLY).json()
    last_ts = events[-1]["timestamp"]
    later = client.get("/audit", params={"since": "2099-01-01T00:00:00Z"}, headers=READONLY).json()
    assert later == []
    again = client.get("/audit", params={"since": last_ts}, headers=READONLY).json()
    assert len(again) >= 1
