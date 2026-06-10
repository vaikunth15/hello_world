# signals/ — Strategies

## Invariants

- Strategies are **pure functions**: `generate(bars, macro) -> Signal`.
  No I/O, no clock, no randomness, no state between calls. The Donchian
  channel position is *replayed* from the bar history on every call so the
  function stays stateless and golden-file testable.
- `generate` returns the **desired direction after today's close**; the
  caller diffs it against the live position. Strategies never size positions
  and never place orders — that is the risk engine's and OrderManager's job.
- Daily bars only in v1; one evaluation per instrument per day (post-close).
- The macro regime filter gates entries only. Exits are never filtered —
  a position whose regime disappears gets flattened, not held.
- Every emitted signal is logged with a full input snapshot for replay
  (handled by the caller's audit log).
