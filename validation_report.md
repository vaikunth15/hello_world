# GOLDGUARD Validation Report

Generated: 2026-06-10T12:37:45+00:00
Data source: SYNTHETIC seeded series (`goldguard.data.synthetic`, seed=7)
Bars: 2000 daily, 2018-01-02 → 2025-09-01
Costs: $1.24/side, 1 tick slippage (4 on event days)

> **⚠ NOT VALID FOR THE PHASE GATE.** This run used the synthetic
> fallback series (no market-data host is reachable from this
> environment). Re-run with `--bars <real-continuous-contract.csv>`
> and document the data vendor and roll method before Phase 3 sign-off.

## Full-history results

### Donchian 55/20 (primary)

| metric | value |
|---|---|
| initial_equity | 100000.0 |
| final_equity | 101585.05 |
| total_return_pct | 1.59 |
| cagr_pct | 0.21 |
| sharpe | 0.18 |
| max_drawdown_pct | 1.93 |
| trades | 159 |
| win_rate_pct | 52.8 |
| avg_win | 205.22 |
| avg_loss | -211.34 |
| total_costs | 394.32 |
| rejected_entries | 0 |
| final_state | RUNNING |

### EMA 20/50 + ADX (benchmark)

| metric | value |
|---|---|
| initial_equity | 100000.0 |
| final_equity | 95537.95 |
| total_return_pct | -4.46 |
| cagr_pct | -0.61 |
| sharpe | -0.32 |
| max_drawdown_pct | 6.05 |
| trades | 378 |
| win_rate_pct | 47.4 |
| avg_win | 194.37 |
| avg_loss | -199.61 |
| total_costs | 937.44 |
| rejected_entries | 27 |
| final_state | RUNNING |

## Parameter sensitivity (±20%, Donchian)

| variation | total return % | flagged (>50% degradation) |
|---|---|---|
| base (55/20/2.0) | 1.59 | no |
| entry_window=44 | -0.58 | **YES** |
| entry_window=66 | 1.61 | no |
| exit_window=16 | 1.66 | no |
| exit_window=24 | -1.07 | **YES** |
| stop_atr_multiple=1.6 | 2.27 | no |
| stop_atr_multiple=2.4 | 3.06 | no |

## Walk-forward (train 3y, test 1y, rolled annually)

- Out-of-sample years: 4 (3 positive)
- Mean OOS annual return: 0.44%

| test window | entry window chosen | OOS return % | max DD % | trades |
|---|---|---|---|---|
| 2020-11-25 → 2021-11-11 | 70 | -0.81 | 1.0 | 4 |
| 2021-11-12 → 2022-10-31 | 70 | 0.01 | 0.35 | 7 |
| 2022-11-01 → 2023-10-18 | 70 | 0.6 | 0.72 | 18 |
| 2023-10-19 → 2024-10-04 | 55 | 1.98 | 1.03 | 38 |

## Notes

- Same code path as live: strategy → RiskEngine.evaluate → simulated
  bracket execution with broker-side stop checked intrabar.
- Weekend flatten (Friday 16:00 ET) and the full drawdown ladder are
  active during the backtest.
- Roll method for real data: back-adjusted continuous contract,
  rolled on volume; document the vendor when supplying `--bars`.

```json
{
 "walk_forward": {
  "folds": [
   {
    "train_start": "2018-01-02",
    "test_start": "2020-11-25",
    "test_end": "2021-11-11",
    "chosen_entry_window": 70,
    "train_scores": {
     "40": 0.39,
     "55": 0.83,
     "70": 1.04
    },
    "test": {
     "initial_equity": 100000.0,
     "final_equity": 99193.82,
     "total_return_pct": -0.81,
     "cagr_pct": -0.84,
     "sharpe": -1.57,
     "max_drawdown_pct": 1.0,
     "trades": 4,
     "win_rate_pct": 0.0,
     "avg_win": 0.0,
     "avg_loss": -202.79,
     "total_costs": 9.92,
     "rejected_entries": 0,
     "final_state": "RUNNING"
    }
   },
   {
    "train_start": "2018-12-20",
    "test_start": "2021-11-12",
    "test_end": "2022-10-31",
    "chosen_entry_window": 70,
    "train_scores": {
     "40": -1.68,
     "55": -0.78,
     "70": -0.66
    },
    "test": {
     "initial_equity": 100000.0,
     "final_equity": 100009.72,
     "total_return_pct": 0.01,
     "cagr_pct": 0.01,
     "sharpe": 0.02,
     "max_drawdown_pct": 0.35,
     "trades": 7,
     "win_rate_pct": 71.4,
     "avg_win": 111.12,
     "avg_loss": -277.28,
     "total_costs": 17.36,
     "rejected_entries": 0,
     "final_state": "RUNNING"
    }
   },
   {
    "train_start": "2019-12-09",
    "test_start": "2022-11-01",
    "test_end": "2023-10-18",
    "chosen_entry_window": 70,
    "train_scores": {
     "40": -2.54,
     "55": -0.94,
     "70": -0.65
    },
    "test": {
     "initial_equity": 100000.0,
     "final_equity": 100604.52,
     "total_return_pct": 0.6,
     "cagr_pct": 0.63,
     "sharpe": 0.58,
     "max_drawdown_pct": 0.72,
     "trades": 18,
     "win_rate_pct": 55.6,
     "avg_win": 144.72,
     "avg_loss": -108.13,
     "total_costs": 44.64,
     "rejected_entries": 0,
     "final_state": "RUNNING"
    }
   },
   {
    "train_start": "2020-11-25",
    "test_start": "2023-10-19",
    "test_end": "2024-10-04",
    "chosen_entry_window": 55,
    "train_scores": {
     "40": -0.3,
     "55": 0.78,
     "70": 0.22
    },
    "test": {
     "initial_equity": 100000.0,
     "final_equity": 101975.63,
     "total_return_pct": 1.98,
     "cagr_pct": 2.06,
     "sharpe": 1.27,
     "max_drawdown_pct": 1.03,
     "trades": 38,
     "win_rate_pct": 60.5,
     "avg_win": 225.91,
     "avg_loss": -217.98,
     "total_costs": 94.24,
     "rejected_entries": 0,
     "final_state": "RUNNING"
    }
   }
  ],
  "oos_mean_annual_return_pct": 0.44,
  "oos_positive_years": 3,
  "oos_years": 4
 }
}
```
