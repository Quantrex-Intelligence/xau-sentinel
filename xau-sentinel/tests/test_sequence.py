"""M5 entry-sequence tracking (Stage 23A, VAL-008/009/018): sweep -> MSS ->
displacement -> retracement, each on its own CLOSED bar and in order. Real,
unmocked synthetic candles throughout."""
import pandas as pd

from analysis.liquidity import LiquidityEvent
from analysis.sequence import evaluate_sequence
from analysis.structure import detect_displacement
from tests.conftest import make_candles

QUIET = [(100.0, 100.3, 99.7, 100.1 if i % 2 == 0 else 99.9) for i in range(20)]
SWING_HIGH = [  # a single, strict swing high of 101.2 at index 22
    (100.0, 100.4, 99.8, 100.2), (100.2, 100.7, 100.0, 100.5), (100.5, 101.2, 100.3, 100.6),
    (100.6, 100.7, 100.1, 100.2), (100.2, 100.4, 99.7, 99.9), (99.9, 100.3, 99.6, 99.8),
]
DECLINE = [(99.8, 99.9, 99.5, 99.6), (99.6, 99.7, 99.2, 99.3), (99.3, 99.4, 99.0, 99.1),
           (99.1, 99.2, 98.9, 99.0)]
SWEEP = [(99.0, 99.4, 98.0, 99.3)]                    # idx 30 — wicks to 98.0, closes back up
PAUSE = [(99.3, 99.7, 99.2, 99.6)]                    # idx 31
DISPLACEMENT_MSS = [(99.6, 101.9, 99.5, 101.8)]       # idx 32 — big body, closes above 101.2
FOLLOW = [(101.8, 102.3, 101.6, 102.0)]               # idx 33 — impulse high 102.3
RETRACE = [(101.2, 101.3, 100.7, 100.8)]              # idx 34 — (102.3-100.8)/(102.3-98.0) ~= 35%

FULL = QUIET + SWING_HIGH + DECLINE + SWEEP + PAUSE + DISPLACEMENT_MSS + FOLLOW + RETRACE
SWEEP_IDX, MSS_IDX = 30, 32


def _df(rows):
    return make_candles(rows)


def _sweep(df, idx=SWEEP_IDX, kind="sweep_low"):
    return LiquidityEvent(df["time"].iloc[idx], "Asian Low swept", "Asian Low", 98.8, kind)


def _mirror(rows, pivot=200.0):
    return [(pivot - o, pivot - l, pivot - h, pivot - c) for o, h, l, c in rows]


def test_full_sequence_across_separate_bars_is_recognized():
    """VAL-009: MSS + displacement on bar 32, retracement on bar 34. The old
    code needed all three on the literal latest bar, which never happens here."""
    df = _df(FULL)
    assert detect_displacement(df) is None  # the latest bar is the retracement, not an impulse

    seq = evaluate_sequence(df, _sweep(df), "BUY")
    assert seq.sweep_index == SWEEP_IDX
    assert seq.mss_level == 101.2
    assert seq.mss_index == MSS_IDX
    assert seq.displacement_index == MSS_IDX
    assert seq.retracement_ok is True
    assert 0.34 < seq.retrace_pct < 0.36
    assert seq.invalidated is False
    assert seq.mss_ok and seq.displacement_ok


def test_retracement_on_or_before_the_displacement_bar_does_not_count():
    df = _df(FULL[:MSS_IDX + 1])  # latest bar IS the displacement/MSS bar
    seq = evaluate_sequence(df, _sweep(df), "BUY")
    assert seq.mss_index == MSS_IDX and seq.displacement_index == MSS_IDX
    assert seq.retracement_ok is False
    assert seq.retrace_pct is None


def test_shallow_pullback_after_displacement_is_not_yet_a_retracement():
    df = _df(FULL[:MSS_IDX + 2])  # latest = FOLLOW, ~7% off the high
    seq = evaluate_sequence(df, _sweep(df), "BUY")
    assert seq.retracement_ok is False
    assert seq.retrace_pct < 0.2


def test_bearish_precursor_before_the_mss_is_not_an_invalidation():
    """VAL-008: right after a low sweep, before any MSS, M5 is naturally in
    a bearish leg. That is the setup's precursor, not an opposing break."""
    df = _df(FULL[:SWEEP_IDX + 2])
    seq = evaluate_sequence(df, _sweep(df), "BUY")
    assert seq.mss_index is None
    assert seq.invalidated is False


def test_close_back_below_the_swept_low_after_the_mss_invalidates_and_stays_invalidated():
    broken = FULL + [(100.8, 100.9, 97.4, 97.5)]  # closes below the 98.0 sweep low
    df = _df(broken)
    seq = evaluate_sequence(df, _sweep(df), "BUY")
    assert seq.invalidated is True
    assert "98.00" in seq.invalidation_reason
    assert not seq.mss_ok and not seq.displacement_ok and not seq.retracement_ok

    # Sticky: a recovery on the next bar does not resurrect the same candidate.
    recovered = broken + [(97.5, 101.0, 97.4, 100.9)]
    df2 = _df(recovered)
    assert evaluate_sequence(df2, _sweep(df2), "BUY").invalidated is True


def test_wick_below_swept_low_without_a_close_is_not_invalidation():
    df = _df(FULL + [(100.8, 100.9, 97.9, 100.5)])
    assert evaluate_sequence(df, _sweep(df), "BUY").invalidated is False


def test_sell_sequence_is_the_exact_mirror():
    df = _df(_mirror(FULL))
    seq = evaluate_sequence(df, _sweep(df, kind="sweep_high"), "SELL")
    assert seq.mss_index == MSS_IDX
    assert seq.mss_level == 98.8  # 200 - 101.2
    assert seq.displacement_index == MSS_IDX
    assert seq.retracement_ok is True
    assert seq.invalidated is False


def test_no_sweep_or_unknown_sweep_bar_yields_empty_result():
    df = _df(FULL)
    assert evaluate_sequence(df, None, "BUY").sweep_index is None
    stray = LiquidityEvent(pd.Timestamp("2020-01-01", tz="UTC"), "x", "Asian Low", 1.0, "sweep_low")
    assert evaluate_sequence(df, stray, "BUY").sweep_index is None
