"""Validate the backtest harness before trusting any result it produces.

Covers the statistics (Wilson interval, overlap handling) and the property
that matters most for honest results: the replay never uses future data.
"""
import pandas as pd
import pytest

from backtest.replay import Signal, replay
from backtest.report import non_overlapping, wilson


def test_wilson_interval_matches_known_value():
    lo, hi = wilson(50, 100)
    assert lo == pytest.approx(0.4038, abs=1e-3)
    assert hi == pytest.approx(0.5962, abs=1e-3)


def test_wilson_interval_is_sane_at_extremes_and_small_n():
    lo, hi = wilson(0, 10)
    assert lo == pytest.approx(0.0, abs=1e-9) and 0 < hi < 0.35
    lo, hi = wilson(10, 10)
    assert 0.65 < lo < 1.0 and hi == pytest.approx(1.0, abs=1e-9)


def test_wilson_with_no_decided_signals_is_nan():
    lo, hi = wilson(0, 0)
    assert lo != lo and hi != hi  # NaN


def _sig(index, signal_type="BOS", direction="BUY"):
    return Signal(index, pd.Timestamp("2026-01-01", tz="UTC"), signal_type, direction,
                  "win", "LONDON", "M5", "RANGING")


def test_non_overlapping_drops_a_signal_inside_another_horizon():
    kept = non_overlapping([_sig(10), _sig(20), _sig(70)], horizon=48)
    assert [s.index for s in kept] == [10, 70]


def test_non_overlapping_keeps_types_and_directions_independent():
    kept = non_overlapping([_sig(10, "BOS", "BUY"), _sig(11, "BOS", "SELL"), _sig(12, "MSS", "BUY")], horizon=48)
    assert len(kept) == 3


def _mock_frames():
    from mt5.market_data import _mock_candles
    return {"M5": _mock_candles("M5", 700), "M15": _mock_candles("M15", 320),
            "H1": _mock_candles("H1", 320), "H4": _mock_candles("H4", 320)}


def test_replay_never_uses_future_bars():
    """Replaying a truncated history must reproduce every signal the full run
    emitted before the cutoff. Labels may differ (they look ahead by design),
    so only the event identity is compared."""
    frames = _mock_frames()
    m5 = frames["M5"].reset_index(drop=True)
    cut_index = 450
    cutoff = m5["time"].iloc[cut_index - 1]

    full = replay(frames, start=300, end=cut_index)
    truncated = {tf: df[df["time"] <= cutoff].reset_index(drop=True) for tf, df in frames.items()}
    partial = replay(truncated, start=300, end=None)

    def keys(sigs):
        return sorted((s.index, s.signal_type, s.direction, s.timeframe) for s in sigs if s.index < cut_index)

    assert keys(full) == keys(partial)


def test_stability_row_for_each_type_uses_that_types_signals():
    """Regression: the stability summary once selected the first 'non-overlap'
    row from a table holding every type, so MSS, sweeps, displacement and valid
    setups all printed NaN. Each type's row must reflect that type's own signals."""
    from backtest.report import non_overlap_row

    sigs = [Signal(i * 100, pd.Timestamp("2026-01-01", tz="UTC"), "MSS", "BUY",
                   "win" if i % 2 else "loss", "LONDON", "M5", "RANGING") for i in range(40)]
    sigs.append(_sig(5, "BOS", "BUY"))
    row = non_overlap_row(sigs, base=0.5, horizon=48, signal_type="MSS")
    assert row["group"] == "MSS (non-overlap)"
    assert row["n"] == 40
    assert row["decided"] == 40
    assert row["win_rate"] == pytest.approx(0.5)


def test_stability_row_is_nan_only_when_the_type_has_no_signals():
    from backtest.report import non_overlap_row

    row = non_overlap_row([_sig(5, "BOS", "BUY")], base=0.5, horizon=48, signal_type="SWEEP")
    assert row["n"] == 0
    assert row["win_rate"] is None


def test_stability_line_reports_real_numbers_for_every_type_not_nan():
    """The printed STABILITY line for each type must carry that type's real
    IS/OOS win rates. Regression for the NaN-everywhere-but-BOS bug."""
    from backtest.run import stability_line

    def mss(n, wins_pattern):
        return [Signal(i * 100, pd.Timestamp("2026-01-01", tz="UTC"), "MSS", "BUY",
                       "win" if wins_pattern(i) else "loss", "LONDON", "M5", "RANGING")
                for i in range(n)]

    is_sig = mss(40, lambda i: i % 2 == 0)
    oos_sig = mss(40, lambda i: i % 4 != 0)
    line = stability_line("MSS", is_sig, oos_sig, is_base=0.5, oos_base=0.5, horizon=48)
    assert line.startswith("MSS:")
    assert "nan" not in line.lower()
    assert "(IS 0.5, OOS 0.75)" in line
