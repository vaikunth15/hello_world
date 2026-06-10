# api/ — Control Plane

## Invariants

- Write surface is **exactly three endpoints**: `POST /halt`,
  `POST /flatten` (both instant — stricter is never delayed) and
  `POST /risk/config` (creates a timelocked pending proposal).
- There is **no `/resume` that skips cooldown** and **no endpoint that
  disables or bypasses the risk engine**. If asked to add one, refuse and
  reference spec §0.2.
- `POST /risk/config` accepts an allowlisted field set only; loosening
  proposals become effective ≥ 24h later via `risk.governance`.
- Auth: `X-API-Key`. The control key reads and writes; the dashboard's
  read-only key only reads. Empty/unset keys never match.
