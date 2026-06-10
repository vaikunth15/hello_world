"""Generate validation_report.md (spec §7). The Phase 3/7 gates read this.

Usage:
    python -m goldguard.backtest.report [--bars path/to/continuous.csv]

Pass a back-adjusted continuous GC/MGC daily CSV (timestamp,open,high,low,
close,volume) for a real-data report — document the vendor and roll method
when you do. Without ``--bars`` the seeded synthetic series is used and the
report is stamped NOT VALID FOR THE PHASE GATE.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from goldguard.backtest.costs import CostModel
from goldguard.backtest.engine import Backtester
from goldguard.backtest.metrics import summarize
from goldguard.backtest.walkforward import walk_forward
from goldguard.core.models import Timeframe
from goldguard.data.bars import load_bars_csv
from goldguard.data.synthetic import synthetic_gold_bars
from goldguard.risk.config import RiskConfig
from goldguard.signals.donchian import DonchianTrend
from goldguard.signals.ma_cross import MaCross

SENSITIVITY_DEGRADATION_FLAG = 0.50  # spec §7: flag >50% return degradation


def parameter_sensitivity(bars, costs: CostModel) -> list[dict]:
    """±20% on each Donchian parameter, one at a time."""
    base = summarize(Backtester(DonchianTrend(), RiskConfig(), costs).run(bars))
    base_ret = base["total_return_pct"]
    rows = [{"params": "base (55/20/2.0)", "total_return_pct": base_ret, "flagged": False}]
    variations = {
        "entry_window": [44, 66],
        "exit_window": [16, 24],
        "stop_atr_multiple": [1.6, 2.4],
    }
    for param, values in variations.items():
        for v in values:
            strategy = DonchianTrend(**{param: v})
            ret = summarize(Backtester(strategy, RiskConfig(), costs).run(bars))["total_return_pct"]
            degraded = base_ret > 0 and ret < base_ret * (1 - SENSITIVITY_DEGRADATION_FLAG)
            rows.append({"params": f"{param}={v}", "total_return_pct": ret, "flagged": degraded})
    return rows


def generate_report(bars_path: Path | None, out_path: Path) -> str:
    if bars_path is not None:
        bars = load_bars_csv(bars_path, Timeframe.DAILY)
        source = f"`{bars_path}` (user-supplied back-adjusted continuous contract)"
        synthetic = False
    else:
        bars = synthetic_gold_bars(n_days=2000, seed=7)
        source = "SYNTHETIC seeded series (`goldguard.data.synthetic`, seed=7)"
        synthetic = True

    costs = CostModel()
    donchian = summarize(Backtester(DonchianTrend(), RiskConfig(), costs).run(bars))
    ma = summarize(Backtester(MaCross(), RiskConfig(), costs).run(bars))
    sensitivity = parameter_sensitivity(bars, costs)
    wf = walk_forward(bars, costs)

    lines = [
        "# GOLDGUARD Validation Report",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"Data source: {source}",
        f"Bars: {len(bars)} daily, {bars[0].timestamp.date()} → {bars[-1].timestamp.date()}",
        f"Costs: ${costs.commission_per_side}/side, {costs.slip_ticks_normal} tick slippage "
        f"({costs.slip_ticks_event} on event days)",
        "",
    ]
    if synthetic:
        lines += [
            "> **⚠ NOT VALID FOR THE PHASE GATE.** This run used the synthetic",
            "> fallback series (no market-data host is reachable from this",
            "> environment). Re-run with `--bars <real-continuous-contract.csv>`",
            "> and document the data vendor and roll method before Phase 3 sign-off.",
            "",
        ]
    lines += ["## Full-history results", ""]
    for name, summary in (("Donchian 55/20 (primary)", donchian), ("EMA 20/50 + ADX (benchmark)", ma)):
        lines += [f"### {name}", "", "| metric | value |", "|---|---|"]
        lines += [f"| {k} | {v} |" for k, v in summary.items()]
        lines.append("")

    lines += [
        "## Parameter sensitivity (±20%, Donchian)",
        "",
        "| variation | total return % | flagged (>50% degradation) |",
        "|---|---|---|",
    ]
    lines += [
        f"| {r['params']} | {r['total_return_pct']} | {'**YES**' if r['flagged'] else 'no'} |"
        for r in sensitivity
    ]

    lines += [
        "",
        "## Walk-forward (train 3y, test 1y, rolled annually)",
        "",
        f"- Out-of-sample years: {wf['oos_years']} ({wf['oos_positive_years']} positive)",
        f"- Mean OOS annual return: {wf['oos_mean_annual_return_pct']}%",
        "",
        "| test window | entry window chosen | OOS return % | max DD % | trades |",
        "|---|---|---|---|---|",
    ]
    lines += [
        f"| {f['test_start']} → {f['test_end']} | {f['chosen_entry_window']} "
        f"| {f['test']['total_return_pct']} | {f['test']['max_drawdown_pct']} | {f['test']['trades']} |"
        for f in wf["folds"]
    ]
    lines += [
        "",
        "## Notes",
        "",
        "- Same code path as live: strategy → RiskEngine.evaluate → simulated",
        "  bracket execution with broker-side stop checked intrabar.",
        "- Weekend flatten (Friday 16:00 ET) and the full drawdown ladder are",
        "  active during the backtest.",
        "- Roll method for real data: back-adjusted continuous contract,",
        "  rolled on volume; document the vendor when supplying `--bars`.",
        "",
        "```json",
        json.dumps({"walk_forward": wf}, indent=1, default=str),
        "```",
        "",
    ]
    text = "\n".join(lines)
    out_path.write_text(text)
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=Path("validation_report.md"))
    args = parser.parse_args()
    generate_report(args.bars, args.out)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
