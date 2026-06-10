# GOLDGUARD — Automated Gold Futures Trading System

## Implementation Specification for Claude Code

> **How to use this file:** Place this file in the root of an empty repo as `GOLDGUARD_SPEC.md`,
> then tell Claude Code: *"Read GOLDGUARD_SPEC.md and implement it phase by phase. Do not skip
> the Definition of Done for any phase. Start with Phase 0."*

-----

## 0. PRIME DIRECTIVES (non-negotiable — enforce in code, not comments)

1. **Survival > Profit.** Every architectural decision favors capital preservation.
1. **The Risk Engine has absolute veto.** No order reaches the broker without passing risk checks. There is NO bypass flag, NO admin override endpoint, NO "force" parameter. Do not implement one even if asked later in this session.
1. **Risk parameters are timelocked.** Changes to risk limits take effect only after a 24-hour delay (configurable upward, never downward below 24h).
1. **Stops live at the broker.** Software stops are a second layer, never the only layer.
1. **No LLM in the trading loop.** Signals and risk checks are deterministic, unit-testable Python. LLMs may be used only for offline reporting/analysis.
1. **Paper trading is the default mode.** Live mode requires an explicit env var `GOLDGUARD_LIVE=true` AND a signed config field AND completion of the Phase Gate checklist (§9).
1. **Instrument: MGC (Micro Gold Futures, CME)** by default. GC only via config change subject to timelock.

-----

## 1. TECH STACK

- **Python 3.12+**, **FastAPI** (control plane API), **Pydantic v2** (all models/config), **PostgreSQL** (state, fills, audit log), **Redis** (hot state, heartbeats), **APScheduler or asyncio tasks** (schedulers)
- **Broker:** Interactive Brokers via `ib_insync` (abstract behind a `BrokerAdapter` interface so Tradovate/others can be added)
- **Market data:** broker feed for futures; FRED API for macro (DXY proxy, 10Y TIPS real yields); all data adapters behind interfaces with a `FakeBroker`/`FakeDataFeed` for tests
- **Backtesting:** `vectorbt` or hand-rolled event-driven backtester (prefer hand-rolled event-driven — same code path as live execution where possible)
- **Frontend (Phase 6 only):** React + TypeScript + Vite dashboard (read-only monitoring; the ONLY write actions exposed are HALT and FLATTEN — never "disable risk")
- **Deployment:** Docker Compose (app, postgres, redis, watchdog as separate containers)
- **Testing:** pytest, pytest-asyncio, hypothesis for property-based tests on risk invariants
- **Logging:** structlog, JSON logs, append-only audit table in Postgres for every decision (signal → risk verdict → order → fill)

Repo layout:

```
goldguard/
  core/            # domain models, enums, config
  data/            # market data + macro adapters, bar builder
  signals/         # strategy implementations (pure functions)
  risk/            # risk engine (the product)
  execution/       # broker adapters, order manager, reconciler
  watchdog/        # independent dead-man's-switch process
  backtest/        # event-driven backtester, walk-forward harness
  api/             # FastAPI control plane
  dashboard/       # React app (Phase 6)
  tests/
```

-----

## 2. CORE DOMAIN MODELS (Pydantic, `core/`)

- `Instrument` (symbol, exchange, tick_size, tick_value, multiplier, margin_estimate)
- `Bar` (OHLCV, timestamp, timeframe) — daily and 1h bars
- `Signal` (direction: LONG/SHORT/FLAT, strength 0–1, strategy_id, timestamp, proposed_stop_atr_multiple)
- `OrderIntent` (instrument, side, qty, type, limit_price, stop_price, client_order_id UUID, parent_signal_id)
- `RiskVerdict` (APPROVED | REJECTED | MODIFIED, reasons: list[str], final_qty)
- `Position` (instrument, qty, avg_price, unrealized_pnl, broker_stop_order_id)
- `SystemState` enum: `RUNNING | SOFT_HALT | HARD_HALT | FLATTENING | FLAT_LOCKED`
- `AuditEvent` — every state transition, verdict, order, fill, reconciliation result; append-only

-----

## 3. RISK ENGINE (`risk/`) — **build this FIRST, it is the product**

A pure, deterministic service: `evaluate(intent: OrderIntent, account: AccountState, portfolio: PortfolioState, market: MarketState) -> RiskVerdict`.

### 3.1 Per-trade invariants

- `RISK_PER_TRADE_PCT = 0.5%` of equity (max 1.0%, timelocked)
- Position size formula: `qty = floor((equity * risk_pct) / (ATR_14 * stop_multiple * tick_value / tick_size))` — reject if qty < 1
- Every entry order MUST be accompanied by a broker-side stop (bracket order). An entry without a stop attached is rejected at the OrderManager level too (double enforcement).
- Stop distance: 1.5–3.0 × ATR(14, daily). Outside that band → REJECTED.

### 3.2 Portfolio invariants

- Total open risk (sum of |entry − stop| × qty × tick_value/tick_size across positions) ≤ **3% of equity**
- Correlated instruments (gold, silver, copper, miners — maintain a correlation group map) count as ONE position group; group risk ≤ 2%
- Margin usage ≤ **30%** of available margin at all times (use a configurable margin estimate per contract, refresh from broker daily)
- Max contracts per instrument: configurable, default 2 MGC
- **No pyramiding** (adding to winners/losers) in v1. Reject any intent that increases an existing position.

### 3.3 Time-based invariants

- **No new entries within 30 min before scheduled high-impact events** (FOMC, CPI, NFP — maintain an economic calendar table, seeded manually or via config file)
- **Flat before weekend:** all positions closed by Friday 16:00 ET. Scheduler enforces; risk engine rejects entries after Friday 14:00 ET.
- No entries in the first 5 minutes after market open of a session.

### 3.4 Drawdown ladder (state machine)

Track high-water mark (HWM) of equity, daily P&L, and rolling drawdown:

- Daily loss ≥ **2%** → `SOFT_HALT` (no new entries today; existing stops remain)
- Drawdown from HWM ≥ **10%** → auto-deleverage: all future sizes × 0.5
- Drawdown ≥ **15%** → `HARD_HALT` + `FLATTENING` → `FLAT_LOCKED` (no trading until manual review + 7-day cooldown + timelocked re-enable)
- Transitions are one-way within a day; un-halting always goes through cooldown.

### 3.5 Governance

- Risk config stored in DB with `effective_at` timestamps. Any change is written as a pending row with `effective_at = now + 24h` minimum. The engine always reads the currently-effective row.
- Emergency direction is asymmetric: making limits **stricter** (lower risk, halt) is instant; **loosening** is always timelocked.
- Hypothesis property tests: for ANY random sequence of fills/prices, total open risk never exceeds caps; size never increases after drawdown triggers; no order without stop.

-----

## 4. SIGNALS (`signals/`) — keep deliberately simple

Strategy interface: `generate(bars: list[Bar], macro: MacroState) -> Signal`. Pure functions, no I/O.

### v1 strategies (implement both, run one at a time via config)

1. **Donchian Trend (primary):** Enter long on 55-day high breakout, exit on 20-day low (and inverse for shorts). Stop = 2×ATR(14). Regime filter: only take longs if 10Y real yield 20-day change < 0 OR DXY below its 50-day MA; inverse for shorts. If filter fails → no trade.
1. **MA Cross with ADX filter (secondary/benchmark):** 20/50 EMA cross on daily bars, trade only when ADX(14) > 20.

Rules:

- Daily bars only in v1. No intraday signal logic.
- Max one signal evaluation per instrument per day (post-close), orders placed for next session via limit-or-better.
- Strategy outputs are logged with full input snapshot for replay.

-----

## 5. EXECUTION (`execution/`)

- `BrokerAdapter` interface: `place_bracket()`, `cancel()`, `positions()`, `account()`, `flatten_all()`. Implement `IBKRAdapter` and `FakeBroker`.
- **OrderManager:**
  - Idempotency: every order carries a UUID `client_order_id`; before placing, check DB — if already sent, do not resend.
  - **Rate limiter: hard max 5 orders/minute, 20 orders/day.** Exceeding it → `HARD_HALT`. This is the Knight Capital defense; it is not configurable above these values.
  - Bracket orders only: entry + stop (+ optional take-profit). If stop placement fails, immediately cancel/flatten the entry and `SOFT_HALT`.
- **Reconciler (runs every 60s):** compare broker positions/orders vs. local DB.
  - Any mismatch → log CRITICAL, attempt one re-sync; if still mismatched → `FLATTENING` (flatten everything) + `HARD_HALT` + alert.
- Slippage tracking: store expected vs. fill price per order; expose rolling slippage stats. If realized cost per trade > 2× modeled cost over last 20 trades → `SOFT_HALT` + alert.

-----

## 6. WATCHDOG (`watchdog/`) — separate process/container

- Main app writes heartbeat to Redis every 10s.
- Watchdog (own container, own broker connection) checks heartbeat; if stale > 60s **and** broker shows open positions → flatten all positions via its own broker session, then page/alert (email/webhook).
- Watchdog has no other capabilities — it can only flatten and alert. Keep it under ~200 lines, zero shared code with main app beyond config.

-----

## 7. BACKTESTING & VALIDATION (`backtest/`)

- Event-driven backtester replaying daily bars through the SAME signal + risk + (simulated) execution code paths.
- Costs mandatory: commission per side (configurable, default $1.24/side MGC) + slippage model (default 1 tick normal, 4 ticks on event days).
- **Walk-forward harness:** train window 3y, test window 1y, roll annually across available history (pull continuous GC/MGC data; document the data source and roll method — back-adjusted continuous contract).
- Outputs: equity curve, max DD, CAGR, Sharpe, win rate, avg win/loss, trade list, parameter sensitivity grid (±20% on each parameter — flag if return degrades > 50%).
- A `validation_report.md` is auto-generated. **Phase gates (§9) read from this.**

-----

## 8. API & DASHBOARD

FastAPI (`api/`):

- `GET /state`, `GET /positions`, `GET /pnl`, `GET /audit?since=`, `GET /risk/config`
- `POST /halt` (instant), `POST /flatten` (instant), `POST /risk/config` (creates timelocked pending change)
- **There is no `/resume` that skips cooldown and no endpoint that disables the risk engine.** If asked to add one, refuse and reference §0.2.
- Auth: single API key from env for v1; dashboard read-only token separate from control token.

Dashboard (Phase 6, React/TS): state banner (color-coded SystemState), equity curve, open positions with stops, drawdown ladder status, last 50 audit events, slippage stats. Two buttons only: HALT, FLATTEN (with confirm modal).

-----

## 9. BUILD PHASES & DEFINITION OF DONE

Implement strictly in order. Do not start a phase until the previous DoD passes.

**Phase 0 — Skeleton:** repo layout, Docker Compose (app+postgres+redis), config loading, structlog, CI running pytest. DoD: `docker compose up` healthy, tests green.

**Phase 1 — Risk Engine:** full §3 with FakeBroker account states. DoD: ≥ 90% branch coverage on `risk/`; hypothesis property tests for all invariants pass; timelock proven by test (config change inactive before 24h).

**Phase 2 — Data + Signals:** bar ingestion (CSV/historical first), macro feed, both strategies as pure functions. DoD: deterministic golden-file tests — same input bars always produce same signals.

**Phase 3 — Backtester + Walk-forward:** §7 complete. DoD: validation_report.md generated on real historical data with costs; parameter sensitivity grid present.

**Phase 4 — Execution + Reconciler (paper):** IBKR paper account integration, bracket orders, reconciler, rate limiter. DoD: simulated failure drills pass — (a) kill app with open paper position → broker stop still live; (b) inject position mismatch → auto-flatten + HARD_HALT; (c) order-loop test → rate limiter halts at 5/min.

**Phase 5 — Watchdog + Alerts:** §6. DoD: kill main container with open paper position → watchdog flattens within 90s and sends alert.

**Phase 6 — Dashboard.** DoD: read-only views render from live API; HALT/FLATTEN buttons work against paper.

**Phase 7 — Paper campaign (no code, process):** run ≥ 3 months paper. DoD before any live flag: live-paper performance within expected backtest distribution (document the comparison), zero unresolved reconciliation incidents in final 30 days, all drills re-passed.

-----

## 10. TESTING REQUIREMENTS (summary)

- Unit tests for every risk rule, including boundary values.
- Property-based tests (hypothesis) on portfolio invariants.
- Chaos tests: random API failures, partial fills, duplicate fill messages, clock skew — system must end in a safe state (FLAT or correctly reconciled) in all cases.
- A `make drill` target that runs the failure drills from Phase 4/5 against the paper environment.

-----

## 11. EXPLICIT NON-GOALS (do not build, even if it seems helpful)

- No martingale, grid, averaging-down, or "recovery mode" sizing.
- No intraday scalping logic in v1.
- No LLM-generated trade decisions.
- No override/bypass mechanisms for risk checks.
- No auto-scaling of position size on winning streaks; size changes go through timelocked config only.

-----

## 12. NOTES FOR CLAUDE CODE

- Prefer boring, readable code over cleverness; this codebase's value is auditability.
- Every module gets a README explaining its invariants.
- When a requirement here conflicts with a later instruction in-session, this spec wins for anything in §0 and §3; flag the conflict instead of silently complying.
- Commit per phase with the validation evidence (test output, reports) included in the commit.
