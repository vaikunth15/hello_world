# watchdog/ — Independent Dead-Man's Switch

## Invariants

- Separate container, separate broker session, **zero shared code** with the
  main app beyond environment configuration. Do not import from
  `goldguard.execution`, `goldguard.risk`, etc. here.
- Capabilities are exactly two: **flatten** and **alert**. Nothing else.
  It can never place entries, change config, or un-halt the system.
- Trigger: heartbeat stale > 60s (or never seen) **and** broker shows open
  positions → flatten via its own session, then alert.
- 10s check interval + 60s staleness ⇒ reaction well inside the 90s DoD.
- Keep this module under ~200 lines so it can be audited in one sitting.
