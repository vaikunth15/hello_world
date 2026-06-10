"""The Risk Engine (spec §3). It has absolute veto: the OrderManager refuses
to send anything that did not come out of ``evaluate`` with an allowed
verdict, and there is no bypass parameter anywhere in this codebase.

``evaluate`` is a pure function of its four arguments. The same inputs always
produce the same verdict, which is what lets the backtester and the live loop
share this exact code path.
"""

from __future__ import annotations

import math
from datetime import timedelta
from zoneinfo import ZoneInfo

from goldguard.core.models import OrderIntent, Position, RiskVerdict, Side, SystemState, Verdict
from goldguard.risk.config import RiskConfig
from goldguard.risk.state import AccountState, MarketState, PortfolioState

ET = ZoneInfo("America/New_York")


class RiskEngine:
    def __init__(self, config: RiskConfig):
        self._cfg = config

    def evaluate(
        self,
        intent: OrderIntent,
        account: AccountState,
        portfolio: PortfolioState,
        market: MarketState,
    ) -> RiskVerdict:
        if intent.reduces_position:
            return self._evaluate_exit(intent, portfolio)
        return self._evaluate_entry(intent, account, portfolio, market)

    def _evaluate_exit(self, intent: OrderIntent, portfolio: PortfolioState) -> RiskVerdict:
        """Exits reduce risk and are allowed in every system state, but may
        never flip a position: qty is capped at the open quantity."""
        pos = portfolio.position_in(intent.instrument.symbol)
        if pos is None:
            return RiskVerdict(verdict=Verdict.REJECTED, reasons=["exit: no open position"], final_qty=0)
        closing_side = Side.SELL if pos.qty > 0 else Side.BUY
        if intent.side is not closing_side:
            return RiskVerdict(verdict=Verdict.REJECTED, reasons=["exit: side does not reduce position"], final_qty=0)
        if intent.qty > abs(pos.qty):
            return RiskVerdict(
                verdict=Verdict.MODIFIED,
                reasons=[f"exit qty capped at open position {abs(pos.qty)}"],
                final_qty=abs(pos.qty),
            )
        return RiskVerdict(verdict=Verdict.APPROVED, final_qty=intent.qty)

    def _evaluate_entry(
        self,
        intent: OrderIntent,
        account: AccountState,
        portfolio: PortfolioState,
        market: MarketState,
    ) -> RiskVerdict:
        cfg = self._cfg
        reject: list[str] = []
        symbol = intent.instrument.symbol

        if account.system_state is not SystemState.RUNNING:
            reject.append(f"no entries while {account.system_state}")
        if symbol not in cfg.allowed_instruments:
            reject.append(f"instrument {symbol} not allowed (timelocked config)")

        # Broker-side stop is mandatory and must be on the losing side (spec §3.1).
        if intent.stop_price is None:
            reject.append("entry without broker-side stop")
        elif intent.limit_price is None:
            reject.append("entry without limit price reference")
        else:
            entry = intent.entry_price
            stop_ok = intent.stop_price < entry if intent.side is Side.BUY else intent.stop_price > entry
            if not stop_ok:
                reject.append("stop is not on the losing side of entry")
            else:
                distance = abs(entry - intent.stop_price)
                atr_multiple = distance / market.atr_14
                if not (cfg.stop_atr_min <= atr_multiple <= cfg.stop_atr_max):
                    reject.append(
                        f"stop distance {atr_multiple:.2f}xATR outside "
                        f"[{cfg.stop_atr_min}, {cfg.stop_atr_max}]"
                    )

        reject.extend(self._time_violations(market))

        existing = portfolio.position_in(symbol)
        if existing is not None:
            reject.append("pyramiding/position change while position open (flatten first)")

        if reject:
            return RiskVerdict(verdict=Verdict.REJECTED, reasons=reject, final_qty=0)

        return self._size(intent, account, portfolio)

    def _time_violations(self, market: MarketState) -> list[str]:
        cfg = self._cfg
        out: list[str] = []
        now_et = market.now.astimezone(ET)
        if now_et.weekday() == 4 and now_et.hour >= cfg.friday_entry_cutoff_hour_et:
            out.append(f"no entries after Friday {cfg.friday_entry_cutoff_hour_et}:00 ET")
        if now_et.weekday() == 5:
            out.append("no entries on Saturday")
        for ev in market.upcoming_events:
            delta = ev.timestamp - market.now
            if timedelta(0) <= delta <= timedelta(minutes=cfg.event_blackout_minutes):
                out.append(f"within {cfg.event_blackout_minutes}min before {ev.name}")
        if market.session_open is not None:
            since_open = market.now - market.session_open
            if timedelta(0) <= since_open < timedelta(minutes=cfg.session_open_blackout_minutes):
                out.append(f"within first {cfg.session_open_blackout_minutes}min of session")
        return out

    def _size(self, intent: OrderIntent, account: AccountState, portfolio: PortfolioState) -> RiskVerdict:
        """Position sizing plus portfolio caps (spec §3.1–3.2). Returns the
        largest qty <= intent.qty that satisfies every cap, or REJECTED."""
        cfg = self._cfg
        inst = intent.instrument
        assert intent.stop_price is not None  # checked in _evaluate_entry
        risk_per_contract = abs(intent.entry_price - intent.stop_price) * inst.point_value

        risk_budget = account.equity * cfg.risk_per_trade_pct * account.size_multiplier
        allowed = math.floor(risk_budget / risk_per_contract)

        caps: list[str] = []
        max_contracts = cfg.max_contracts.get(inst.symbol)
        if max_contracts is not None and allowed > max_contracts:
            allowed = max_contracts
            caps.append(f"capped at max {max_contracts} contracts")

        portfolio_headroom = cfg.portfolio_risk_cap_pct * account.equity - portfolio.total_open_risk
        group = cfg.group_of(inst.symbol)
        group_risk = sum(
            p.open_risk for p in portfolio.positions if cfg.group_of(p.instrument.symbol) == group
        )
        group_headroom = cfg.group_risk_cap_pct * account.equity - group_risk
        risk_headroom = min(portfolio_headroom, group_headroom)
        if allowed * risk_per_contract > risk_headroom:
            allowed = max(0, math.floor(risk_headroom / risk_per_contract))
            caps.append("capped by portfolio/group open-risk limit")

        margin_headroom = cfg.margin_cap_pct * account.margin_capacity - account.margin_used
        if allowed * inst.margin_estimate > margin_headroom:
            allowed = max(0, math.floor(margin_headroom / inst.margin_estimate))
            caps.append("capped by margin usage limit")

        if allowed < 1:
            return RiskVerdict(
                verdict=Verdict.REJECTED,
                reasons=caps + ["sized quantity < 1 contract"],
                final_qty=0,
            )
        if allowed < intent.qty:
            return RiskVerdict(verdict=Verdict.MODIFIED, reasons=caps or ["qty reduced to risk budget"], final_qty=allowed)
        return RiskVerdict(verdict=Verdict.APPROVED, final_qty=intent.qty)
