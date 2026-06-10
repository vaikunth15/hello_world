# GOLDGUARD Phase Gate Checklist

This file is read by `core/config.py`: live mode is impossible until **every**
box below is checked (`- [x]`), in addition to `GOLDGUARD_LIVE=true` and a
valid signed config. Check a box only with evidence linked next to it.

## Phase 3 — Validation

- [ ] `validation_report.md` regenerated on REAL back-adjusted continuous
      GC/MGC data (vendor and roll method documented in the report)
- [ ] Parameter sensitivity grid shows no >50% degradation flag, or the flag
      is reviewed and accepted in writing
- [ ] Walk-forward out-of-sample results reviewed

## Phase 4/5 — Operational drills (against IBKR paper)

- [ ] Drill (a): app killed with open paper position → broker stop verified
      live at IBKR
- [ ] Drill (b): injected position mismatch → auto-flatten + HARD_HALT
- [ ] Drill (c): order loop → rate limiter halts at 5/min
- [ ] Watchdog drill: main container killed with open paper position →
      flattened within 90s + alert received

## Phase 7 — Paper campaign (≥ 3 months)

- [ ] ≥ 3 calendar months of paper trading completed
- [ ] Paper performance within expected backtest distribution
      (comparison documented in `docs/PAPER_CAMPAIGN.md` results section)
- [ ] Zero unresolved reconciliation incidents in the final 30 days
- [ ] All drills re-passed in the final week
- [ ] Manual review signoff recorded below

Signoff: _name, date, notes_
