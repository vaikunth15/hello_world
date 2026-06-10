# execution/ — Broker Adapters, OrderManager, Reconciler

## Invariants

- **The OrderManager only sends what the risk engine approved**, at the
  verdict's `final_qty`. There is no path to the broker around it.
- **Bracket orders only.** An entry without a stop is rejected here even if
  it somehow got past the risk engine (double enforcement). On IBKR the stop
  is a native child order resting at the broker — it survives an app crash.
- **Rate limiter** (Knight Capital defense): hard max 5 orders/minute and
  20/day. The limits are module constants, not configuration. Exceeding
  either → the order is not sent and the system HARD_HALTs.
- **Idempotency:** every order carries a UUID `client_order_id`; one that
  was ever marked sent is never re-sent.
- **Stop placement failure** → the entry is flattened immediately and the
  system SOFT_HALTs. A stopless position never survives.
- **Reconciler** (every 60s): broker truth vs local book; one re-sync
  attempt, then flatten-all + HARD_HALT + alert.
- **Slippage tracker:** duplicate fill messages are counted once; realized
  cost > 2× modeled over the last 20 trades → SOFT_HALT + alert.
