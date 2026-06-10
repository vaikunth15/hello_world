# risk/ — The Risk Engine

This module is the product. Everything else exists to feed it inputs and obey
its verdicts.

## Invariants

- `RiskEngine.evaluate(intent, account, portfolio, market)` is a **pure
  function**: no I/O, no clock reads (`market.now` is the only time source),
  no randomness. Same inputs ⇒ same verdict, in live trading and in backtest.
- **No bypass exists.** There is no force flag, no admin override, no
  endpoint that disables checks. Do not add one (spec §0.2).
- Every approved entry has a broker-side stop within 1.5–3.0 × ATR(14).
- Per-trade risk ≤ `risk_per_trade_pct` (default 0.5%, hard ceiling 1.0%
  enforced by the Pydantic model itself).
- Total open risk ≤ 3% of equity; correlated-group risk ≤ 2%; margin usage
  ≤ 30%; ≤ 2 contracts MGC; no pyramiding.
- Time blackouts: 30 min before high-impact events, after Friday 14:00 ET,
  first 5 min of a session.
- Exits (`reduces_position=True`) are allowed in **every** system state —
  closing risk is never blocked — but can never flip a position.

## Drawdown ladder (`ladder.py`)

`RUNNING → SOFT_HALT` (daily loss ≥ 2%), deleverage ×0.5 (DD ≥ 10%),
`HARD_HALT → FLATTENING → FLAT_LOCKED` (DD ≥ 15%). One-way within a day.
Leaving `FLAT_LOCKED` takes a manual review signoff **and** a 7-day cooldown
**and** a further 24h timelock (two-step request/confirm).

## Governance (`governance.py`)

Risk config rows carry `effective_at`. Tightening is instant; **any**
loosening delays the whole proposal by ≥ 24h (`timelock_hours`, which can be
raised but never set below 24). The engine only ever reads the currently
effective row.
