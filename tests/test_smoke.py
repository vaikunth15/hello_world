"""Phase 0 smoke tests: config loading defaults to paper, logging configures."""

import hashlib
import hmac

from goldguard.core.config import Settings, TradingMode
from goldguard.core.logging import configure_logging, get_logger


def test_default_mode_is_paper():
    s = Settings(_env_file=None)
    assert s.mode is TradingMode.PAPER
    mode, reasons = s.resolve_mode()
    assert mode is TradingMode.PAPER
    assert reasons


def test_live_requires_env_var_even_with_signature(tmp_path, monkeypatch):
    monkeypatch.delenv("GOLDGUARD_LIVE", raising=False)
    gate = tmp_path / "PHASE_GATE.md"
    gate.write_text("- [x] backtest validated\n- [x] 3 months paper\n")
    key = "secret"
    s = Settings(
        _env_file=None,
        mode=TradingMode.LIVE,
        live=True,
        signing_key=key,
        phase_gate_checklist=gate,
    )
    s = s.model_copy(
        update={"live_signature": hmac.new(key.encode(), s.live_payload(), hashlib.sha256).hexdigest()}
    )
    mode, reasons = s.resolve_mode()
    assert mode is TradingMode.PAPER
    assert any("GOLDGUARD_LIVE" in r for r in reasons)


def test_live_granted_only_with_all_three_factors(tmp_path, monkeypatch):
    monkeypatch.setenv("GOLDGUARD_LIVE", "true")
    gate = tmp_path / "PHASE_GATE.md"
    gate.write_text("- [x] backtest validated\n- [x] 3 months paper\n")
    key = "secret"
    s = Settings(
        _env_file=None,
        mode=TradingMode.LIVE,
        live=True,
        signing_key=key,
        phase_gate_checklist=gate,
    )
    s = s.model_copy(
        update={"live_signature": hmac.new(key.encode(), s.live_payload(), hashlib.sha256).hexdigest()}
    )
    mode, reasons = s.resolve_mode()
    assert mode is TradingMode.LIVE
    assert reasons == []


def test_incomplete_phase_gate_blocks_live(tmp_path, monkeypatch):
    monkeypatch.setenv("GOLDGUARD_LIVE", "true")
    gate = tmp_path / "PHASE_GATE.md"
    gate.write_text("- [x] backtest validated\n- [ ] 3 months paper\n")
    key = "secret"
    s = Settings(
        _env_file=None,
        mode=TradingMode.LIVE,
        live=True,
        signing_key=key,
        phase_gate_checklist=gate,
    )
    s = s.model_copy(
        update={"live_signature": hmac.new(key.encode(), s.live_payload(), hashlib.sha256).hexdigest()}
    )
    mode, reasons = s.resolve_mode()
    assert mode is TradingMode.PAPER
    assert any("phase gate" in r for r in reasons)


def test_bad_signature_blocks_live(tmp_path, monkeypatch):
    monkeypatch.setenv("GOLDGUARD_LIVE", "true")
    gate = tmp_path / "PHASE_GATE.md"
    gate.write_text("- [x] all done\n")
    s = Settings(
        _env_file=None,
        mode=TradingMode.LIVE,
        live=True,
        signing_key="secret",
        live_signature="deadbeef",
        phase_gate_checklist=gate,
    )
    mode, reasons = s.resolve_mode()
    assert mode is TradingMode.PAPER
    assert any("signature" in r for r in reasons)


def test_logging_configures_and_emits(capsys):
    configure_logging()
    get_logger("test").info("hello", phase=0)
    out = capsys.readouterr().out
    assert '"hello"' in out and '"phase": 0' in out
