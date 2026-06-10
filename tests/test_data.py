"""Bar ingestion and macro state construction."""

from datetime import date

import pytest

from goldguard.data.bars import load_bars_csv, validate_bars
from goldguard.data.macro import CsvMacroSource, MacroState, build_macro_state
from goldguard.data.synthetic import synthetic_gold_bars


def test_load_bars_csv(tmp_path):
    p = tmp_path / "mgc.csv"
    p.write_text(
        "timestamp,open,high,low,close,volume\n"
        "2026-01-05T17:00:00+00:00,2000,2010,1990,2005,1000\n"
        "2026-01-06T17:00:00+00:00,2005,2015,2000,2012,1200\n"
    )
    bars = load_bars_csv(p)
    assert len(bars) == 2
    assert bars[1].close == 2012


def test_naive_timestamp_rejected(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("timestamp,open,high,low,close,volume\n2026-01-05T17:00:00,1,2,0.5,1.5,0\n")
    with pytest.raises(ValueError, match="naive"):
        load_bars_csv(p)


def test_out_of_order_bars_rejected(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text(
        "timestamp,open,high,low,close,volume\n"
        "2026-01-06T17:00:00+00:00,1,2,0.5,1.5,0\n"
        "2026-01-05T17:00:00+00:00,1,2,0.5,1.5,0\n"
    )
    with pytest.raises(ValueError, match="increasing"):
        load_bars_csv(p)


def test_inconsistent_ohlc_rejected(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("timestamp,open,high,low,close,volume\n2026-01-05T17:00:00+00:00,1,2,0.5,9,0\n")
    with pytest.raises(ValueError, match="OHLC"):
        load_bars_csv(p)


def test_synthetic_bars_are_deterministic_and_valid():
    a = synthetic_gold_bars(n_days=300, seed=7)
    b = synthetic_gold_bars(n_days=300, seed=7)
    assert a == b
    validate_bars(a)
    assert synthetic_gold_bars(n_days=300, seed=8) != a


def test_macro_state_fails_closed_without_data():
    m = MacroState()
    assert not m.long_regime_ok()
    assert not m.short_regime_ok()


def test_build_macro_state_and_regimes():
    days = [date(2026, 1, 1)] * 60  # dates unused by the math
    falling = build_macro_state(
        real_yield=list(zip(days, [2.0 - 0.01 * i for i in range(60)])),
        dxy=list(zip(days, [100.0] * 60)),
    )
    assert falling.real_yield_20d_change == pytest.approx(-0.20)
    assert falling.long_regime_ok() and not falling.short_regime_ok()

    rising = build_macro_state(
        real_yield=list(zip(days, [2.0 + 0.01 * i for i in range(60)])),
        dxy=list(zip(days, [100.0 + 0.1 * i for i in range(60)])),
    )
    assert rising.short_regime_ok() and not rising.long_regime_ok()


def test_build_macro_state_insufficient_history():
    days = [date(2026, 1, 1)] * 10
    m = build_macro_state(
        real_yield=list(zip(days, [2.0] * 10)), dxy=list(zip(days, [100.0] * 10))
    )
    assert m.real_yield_20d_change is None and m.dxy is None


def test_csv_macro_source_skips_fred_missing_markers(tmp_path):
    (tmp_path / "DFII10.csv").write_text(
        "date,value\n2026-01-05,2.1\n2026-01-06,.\n2026-01-07,2.2\n"
    )
    series = CsvMacroSource(tmp_path).series("DFII10", limit=10)
    assert series == [(date(2026, 1, 5), 2.1), (date(2026, 1, 7), 2.2)]
