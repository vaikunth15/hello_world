# Phase 7 — Paper Trading Campaign (process)

Run the full system against an IBKR **paper** account for at least 3 months
before even considering the live flag. This document is the operating
procedure and the results log.

## Setup

1. `docker compose up` with `GOLDGUARD_MODE=paper` (the default; live is
   triple-gated and will silently degrade to paper anyway).
2. IBKR Gateway/TWS in paper mode on the configured host/port; watchdog
   container connected with its own `clientId`.
3. Alert webhook configured (`GOLDGUARD_ALERT_WEBHOOK_URL`) and tested.
4. Economic calendar JSON seeded for the whole campaign window (FOMC, CPI,
   NFP) and refreshed monthly.

## Weekly routine

- Verify reconciler logs show zero unresolved mismatches.
- Verify weekend flatten happened every Friday (audit log).
- Export slippage stats; compare realized vs modeled cost.
- Snapshot `/pnl` and `/audit` to the campaign log.

## Monthly routine

- Re-run `python -m goldguard.backtest.report --bars <real-data.csv>` with
  data extended to date; compare live-paper equity curve against the
  backtest distribution over the same window (return, max DD, trade count,
  win rate — each should fall inside the backtest's plausible range; if not,
  STOP and find out why before continuing).
- Re-run all failure drills (`make drill` + watchdog kill test).

## Exit criteria (feed into docs/PHASE_GATE.md)

- ≥ 3 months elapsed.
- Performance within expected backtest distribution — attach the comparison
  table below.
- Zero unresolved reconciliation incidents in the final 30 days.
- All drills re-passed in the final week.

## Results log

| month | paper return % | backtest expected range | max DD % | trades | recon incidents | drills |
|---|---|---|---|---|---|---|
|   |   |   |   |   |   |   |
