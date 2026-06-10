# GOLDGUARD

Automated gold futures (MGC) trading system built to the spec in
[`GOLDGUARD_SPEC.md`](GOLDGUARD_SPEC.md). **Survival > profit**: the risk
engine has absolute veto, stops live at the broker, paper trading is the
default, and live mode is triple-gated.

## Layout

| module | what it is |
|---|---|
| `goldguard/core` | domain models, config (live-mode gating), logging, heartbeat |
| `goldguard/risk` | **the product**: pure risk engine, drawdown ladder, timelocked governance |
| `goldguard/data` | bar/macro ingestion behind protocols; synthetic fallback series |
| `goldguard/signals` | Donchian 55/20 (primary) + EMA 20/50 ADX (benchmark), pure functions |
| `goldguard/execution` | broker adapters (IBKR + fake), OrderManager, reconciler, slippage |
| `goldguard/backtest` | event-driven backtester on the live code path, walk-forward, report |
| `goldguard/watchdog` | independent dead-man's switch (own container, flatten + alert only) |
| `goldguard/api` | FastAPI control plane (halt / flatten / timelocked config proposals) |
| `dashboard/` | React+TS read-only monitor with HALT and FLATTEN buttons |

Each module's README states its invariants. Start with `goldguard/risk/README.md`.

## Quick start

```bash
pip install -e ".[dev]"
pytest                                  # full suite
make cov                                # branch coverage
make drill                              # Phase 4/5 failure drills
python -m goldguard.backtest.report     # validation_report.md (synthetic fallback)
GOLDGUARD_API_KEY=... GOLDGUARD_READONLY_KEY=... docker compose up
cd dashboard && npm install && npm run dev
```

## Safety properties enforced in code (not comments)

- No order reaches a broker without a `RiskVerdict` from the risk engine —
  and the OrderManager re-checks the stop anyway.
- Loosening any risk limit takes ≥ 24h (timelock); tightening is instant.
- Rate limiter: 5 orders/min, 20/day, hard-coded; breach → HARD_HALT.
- Drawdown ladder: −2% day → SOFT_HALT; −10% → half size; −15% → flatten and
  lock, exit only via review + 7-day cooldown + 24h timelock.
- Watchdog flattens from its own broker session if the app stops
  heartbeating while positions are open.
- Live mode requires `GOLDGUARD_LIVE=true` **and** a valid HMAC-signed
  config **and** a fully checked [`docs/PHASE_GATE.md`](docs/PHASE_GATE.md).

## Status

Phases 0–6 implemented with their Definitions of Done; Phase 7 (≥3-month
paper campaign) is a process gate documented in
[`docs/PAPER_CAMPAIGN.md`](docs/PAPER_CAMPAIGN.md). The committed
`validation_report.md` was generated on the synthetic fallback series
(no market-data egress from the build environment) and is stamped
accordingly — regenerate with real continuous-contract data before any gate
decision.
