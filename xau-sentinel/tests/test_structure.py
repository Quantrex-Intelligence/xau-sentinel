"""Market structure validation: swing detection, HH/HL/LH/LL, trend
classification, BOS, MSS, displacement, and look-ahead bias."""
from datetime import datetime, timedelta, timezone

import pandas as pd

import config
from analysis.structure import (
    analyze_structure, closed_only, compute_atr, detect_displacement, displacement_at, find_swing_points, is_feed_stale,
)
from tests.conftest import make_candles


def _ramp_path(points, steps_per_leg):
    """Concatenates straight-line ramps between control points (a synthetic
    zig-zag), one value per bar, oldest first."""
    path = [points[0]]
    for i in range(1, len(points)):
        a, b = points[i - 1], points[i]
        for s in range(1, steps_per_leg + 1):
            path.append(a + (b - a) * s / steps_per_leg)
    return path


def _flat_candles_from_path(path, tail=None, tf_minutes=5):
    """Turns a price path into flat candles (open=high=low=close) so swing
    highs/lows land exactly on the control points with no wick ambiguity."""
    values = list(path) + list(tail or [])
    rows = [(v, v, v, v) for v in values]
    return make_candles(rows, tf_minutes=tf_minutes)


# Control points chosen so every leg is strictly monotonic (no ties) and every
# pivot has >= SWING_LOOKBACK(3) bars on both sides once the tail is appended.
BULLISH_POINTS = [110, 100, 115, 105, 120, 112, 128]  # -> L100, H115, L105(HL), H120(HH), L112(HL), H128(HH)
BEARISH_POINTS = [90, 100, 85, 95, 80, 88, 72]  # mirror: H100, L85, H95(LH), L80(LL), H88(LH), L72(LL)


def test_swing_labels_hh_hl_sequence():
    path = _ramp_path(BULLISH_POINTS[:6], steps_per_leg=7)  # ... H120(HH), L112(HL)
    df = _flat_candles_from_path(path, tail=[113, 114, 115])  # stays above L112 so it remains the pivot low
    swings = find_swing_points(df)
    labeled = [p for p in swings if p.label]
    assert [(p.kind, round(p.price), p.label) for p in labeled] == [
        ("low", 105, "HL"),
        ("high", 120, "HH"),
        ("low", 112, "HL"),
    ]


def test_swing_labels_lh_ll_sequence():
    path = _ramp_path(BEARISH_POINTS[:6], steps_per_leg=7)  # ... L80(LL), H88(LH)
    df = _flat_candles_from_path(path, tail=[87, 86, 85])  # stays below H88 so it remains the pivot high
    swings = find_swing_points(df)
    labeled = [p for p in swings if p.label]
    assert [(p.kind, round(p.price), p.label) for p in labeled] == [
        ("high", 95, "LH"),
        ("low", 80, "LL"),
        ("high", 88, "LH"),
    ]


def test_bullish_structure_hh_hl_classified_bullish():
    path = _ramp_path(BULLISH_POINTS[:5], steps_per_leg=7)
    df = _flat_candles_from_path(path, tail=[112.5, 113, 113.5])  # stays above last HL(112)
    result = analyze_structure(df)
    assert result.state == "BULLISH"
    assert "HH" in result.reason and "HL" in result.reason


def test_bearish_structure_lh_ll_classified_bearish():
    path = _ramp_path(BEARISH_POINTS[:5], steps_per_leg=7)
    df = _flat_candles_from_path(path, tail=[87.5, 87, 86.5])  # stays below last LH(88)
    result = analyze_structure(df)
    assert result.state == "BEARISH"
    assert "LH" in result.reason and "LL" in result.reason


def test_expanding_range_hh_ll_classified_ranging():
    # Higher high AND lower low -> no clean directional structure.
    path = _ramp_path([100, 110, 90, 120, 80], steps_per_leg=7)
    df = _flat_candles_from_path(path, tail=[81, 82, 83])
    result = analyze_structure(df)
    assert result.state == "RANGING"
    assert "Higher high but lower low" in result.reason


def test_contracting_range_lh_hl_classified_ranging():
    # Lower high AND higher low -> compressing range.
    path = _ramp_path([80, 110, 90, 105, 95], steps_per_leg=7)
    df = _flat_candles_from_path(path, tail=[96, 97, 98])  # stays above the L95 pivot, doesn't disturb it
    result = analyze_structure(df)
    assert result.state == "RANGING"
    assert "range compressing" in result.reason


def test_insufficient_history_does_not_force_a_trend():
    df = _flat_candles_from_path([100, 101, 100, 101, 100])
    result = analyze_structure(df)
    assert result.state == "RANGING"
    assert "Not enough" in result.reason or "No clear" in result.reason


def test_bullish_structure_breaking_prior_hl_becomes_pullback_not_forced_bearish():
    """Transition case: a bullish HH/HL structure closes below its last
    higher-low, but a bearish structure is not yet confirmed. Must report an
    explicit transitional state, never a forced BULLISH or BEARISH."""
    path = _ramp_path(BULLISH_POINTS[:6], steps_per_leg=7)  # last low = L112 (HL)
    df = _flat_candles_from_path(path, tail=[104, 102, 100])  # closes below last HL(112)
    result = analyze_structure(df)
    assert result.state == "PULLBACK"
    assert result.last_mss == "bearish"
    assert result.state not in ("BULLISH", "BEARISH")


# ---------------------------------------------------------------------------
# Stage 21 (VAL-006): a still-FORMING candle must never be treated as
# confirmed structure -- reuses the exact scenario above, but makes only
# the final, structure-flipping candle a forming one.
# ---------------------------------------------------------------------------

def test_structure_ignores_a_forming_candle_that_would_otherwise_trigger_pullback():
    path = _ramp_path(BULLISH_POINTS[:6], steps_per_leg=7)  # last confirmed low = L112 (HL)
    closed_tail = [113, 114, 115]  # 3 confirming bars, stays above L112 -> BULLISH once closed
    forming_close = 100  # would trigger the bearish-MSS/PULLBACK branch if treated as closed

    values = list(path) + closed_tail + [forming_close]
    rows = [(v, v, v, v) for v in values]
    start = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)
    now = start + timedelta(minutes=5 * (len(rows) - 1))  # exactly the last row is still forming
    df = make_candles(rows, start=start, now=now)

    # Sanity: if the forming candle WERE (incorrectly) treated as closed,
    # this scenario really would trigger PULLBACK -- proving the test is
    # actually meaningful, not a no-op.
    unfiltered_result = analyze_structure(df)
    assert unfiltered_result.state == "PULLBACK"
    assert unfiltered_result.last_mss == "bearish"

    # The fix: filtering to CLOSED candles first must ignore the forming bar.
    closed_result = analyze_structure(closed_only({"H1": df})["H1"])
    assert closed_result.state == "BULLISH"
    assert closed_result.last_mss is None


def test_bearish_structure_breaking_prior_lh_becomes_pullback():
    path = _ramp_path(BEARISH_POINTS[:6], steps_per_leg=7)  # last high = H88 (LH)
    df = _flat_candles_from_path(path, tail=[96, 97, 98])  # closes above last LH(88)
    result = analyze_structure(df)
    assert result.state == "PULLBACK"
    assert result.last_mss == "bullish"


def test_bos_confirmed_on_close_beyond_latest_swing_high():
    """BOS definition: bullish structure intact AND the latest close trades
    through the LATEST confirmed swing high (the HH) — a confirmed-close
    break, not a wick-only touch (Stage 23A, VAL-013)."""
    path = _ramp_path(BULLISH_POINTS, steps_per_leg=7)  # ends at H128(HH), L112(HL)
    df = _flat_candles_from_path(path, tail=[126, 124, 122, 126, 129])  # 128 stays the pivot; close 129 > 128
    result = analyze_structure(df)
    assert result.state == "BULLISH"
    assert result.last_bos == "bullish"


def test_bos_not_reported_against_superseded_prior_swing_high():
    """VAL-013 regression: the old definition compared against the prior,
    already-superseded swing high (120), so a close of 122 — a retracement
    BELOW the latest HH of 128 — was reported as a bullish BOS."""
    path = _ramp_path(BULLISH_POINTS, steps_per_leg=7)
    df = _flat_candles_from_path(path, tail=[126, 124, 122])  # 120 < 122 < 128
    result = analyze_structure(df)
    assert result.state == "BULLISH"
    assert result.last_bos is None


def test_bearish_bos_measured_against_latest_swing_low():
    path = _ramp_path(BEARISH_POINTS, steps_per_leg=7)  # ends at L72(LL), H88(LH)
    df = _flat_candles_from_path(path, tail=[74, 76, 78])  # 72 < 78 < 80 (the superseded low)
    assert analyze_structure(df).last_bos is None
    df = _flat_candles_from_path(path, tail=[74, 76, 78, 74, 71])
    result = analyze_structure(df)
    assert result.state == "BEARISH"
    assert result.last_bos == "bearish"


def test_bos_not_triggered_by_wick_only_break():
    """A wick that pokes above the prior swing high but closes back below it
    must NOT register as a BOS — only a confirmed close counts."""
    import pandas as pd
    path = _ramp_path(BULLISH_POINTS, steps_per_leg=7)  # matured: last_high=H128(HH), prior_high=120, last_low=L112(HL)
    df = _flat_candles_from_path(path)
    wick_bar = make_candles([(127, 131, 126, 119, 100)])  # high(131) pokes way past prior_high(120), close(119) stays under it
    df = pd.concat([df, wick_bar], ignore_index=True)
    result = analyze_structure(df)
    assert result.last_bos is None


def test_bos_not_triggered_by_false_break_that_reverses():
    """Price pokes to a new extreme intrabar, then reverses and closes back
    under the level it needed to confirm — still no BOS."""
    import pandas as pd
    path = _ramp_path(BULLISH_POINTS, steps_per_leg=7)
    df = _flat_candles_from_path(path)
    poke_and_reverse = make_candles([
        (128, 135, 127, 133, 100),   # pokes to a new high, closes above prior_high (would-be BOS if it were last)
        (133, 134, 115, 117, 100),   # but reverses hard, closing back under prior_high(120)
    ])
    df = pd.concat([df, poke_and_reverse], ignore_index=True)
    result = analyze_structure(df)
    assert result.last_bos is None


def test_displacement_flags_outsized_body_vs_prior_atr():
    baseline = [(100 + i * 0, 100.5, 99.5, 100, 100) for i in range(19)]
    df = make_candles(baseline)
    big_bull = make_candles([(100, 111, 99.5, 110, 100)])  # body=10, way beyond ~1 ATR baseline
    df = __import__("pandas").concat([df, big_bull], ignore_index=True)
    assert detect_displacement(df) == "bullish"

    big_bear = make_candles([(100, 100.5, 89, 90, 100)])  # body=-10
    df2 = __import__("pandas").concat([make_candles(baseline), big_bear], ignore_index=True)
    assert detect_displacement(df2) == "bearish"


def test_normal_candle_is_not_displacement():
    baseline = [(100, 100.5, 99.5, 100, 100) for _ in range(19)]
    df = make_candles(baseline)
    normal = make_candles([(100, 100.6, 99.6, 100.4, 100)])  # body=0.4, well under 1.5x ATR(~1)
    import pandas as pd
    df = pd.concat([df, normal], ignore_index=True)
    assert detect_displacement(df) is None


def test_displacement_never_measures_a_candle_against_its_own_range():
    """The reference ATR must come from *prior* candles only (atr.iloc[-2]),
    so a single huge candle can't inflate the very baseline it's judged
    against."""
    baseline = [(100, 100.5, 99.5, 100, 100) for _ in range(19)]
    huge = make_candles([(100, 200, 100, 190, 100)])  # itself enormous
    import pandas as pd
    df = pd.concat([make_candles(baseline), huge], ignore_index=True)
    atr = compute_atr(df)
    # reference ATR (second-to-last bar) must still reflect the quiet baseline, not the huge candle
    assert atr.iloc[-2] < 2.0
    assert detect_displacement(df) == "bullish"


# ---------------------------------------------------------------------------
# Look-ahead bias audit (spec section 8)
# ---------------------------------------------------------------------------

def test_swing_points_never_repaint_as_more_data_arrives():
    """A swing point that has already matured (has >= SWING_LOOKBACK bars
    after it) must report identically no matter how much future data is
    later appended."""
    path = _ramp_path(BULLISH_POINTS + [118, 140], steps_per_leg=7)
    df = _flat_candles_from_path(path, tail=[141, 142, 143])
    full = find_swing_points(df)

    for cutoff in (25, 32, 40, 50, len(df)):
        prefix = df.iloc[:cutoff]
        partial = find_swing_points(prefix)
        matured = [p for p in full if p.index + config.SWING_LOOKBACK < cutoff]
        assert [(p.index, p.kind, p.price, p.label) for p in partial] == \
               [(p.index, p.kind, p.price, p.label) for p in matured], f"repaint detected at cutoff={cutoff}"


def test_unconfirmed_swing_is_absent_until_lookback_bars_exist_after_it():
    """A swing at candle T that only becomes confirmed at T+lookback must not
    appear in the swing list before that many future bars exist."""
    path = _ramp_path(BULLISH_POINTS[:5], steps_per_leg=7)
    df = _flat_candles_from_path(path, tail=[112.5, 113, 113.5, 114, 115])

    full = find_swing_points(df)
    last_pivot = full[-1]  # the low at index ~28 (label HL)
    t = last_pivot.index

    # Exactly lookback bars after T: still not confirmed (loop excludes it).
    df_insufficient = df.iloc[: t + config.SWING_LOOKBACK]
    swings_insufficient = find_swing_points(df_insufficient)
    assert last_pivot.index not in [p.index for p in swings_insufficient]

    # One more bar: now the window is complete and it must appear.
    df_sufficient = df.iloc[: t + config.SWING_LOOKBACK + 1]
    swings_sufficient = find_swing_points(df_sufficient)
    assert last_pivot.index in [p.index for p in swings_sufficient]


def test_mss_does_not_depend_on_future_candles():
    """analyze_structure's last_mss is derived only from already-matured
    swings plus the *current* last close — appending bars beyond what's
    needed to confirm a given state must not change an MSS determination
    that was already made using only past/present information."""
    path = _ramp_path(BULLISH_POINTS[:6], steps_per_leg=7)
    df = _flat_candles_from_path(path, tail=[104, 102, 100])  # closes below last HL -> bearish MSS
    result_now = analyze_structure(df)
    assert result_now.last_mss == "bearish"

    # Extend with more (future, at the time of the original call) bars and
    # recompute AS OF the same cutoff — the earlier determination must be
    # reproducible from the same prefix regardless of what comes after it.
    extended = pd.concat([df, make_candles([(100, 100.5, 99.5, 100)] * 5)], ignore_index=True)
    result_from_prefix_of_extended = analyze_structure(extended.iloc[: len(df)])
    assert result_from_prefix_of_extended.last_mss == result_now.last_mss
    assert result_from_prefix_of_extended.state == result_now.state


# --- Stage 23A: displacement_at / is_feed_stale -------------------------------

def _quiet_then(rows_after, n_quiet=20):
    rows = [(100.0, 100.3, 99.7, 100.1 if i % 2 == 0 else 99.9) for i in range(n_quiet)]
    return make_candles(rows + list(rows_after))


def test_displacement_at_finds_an_earlier_bar_not_only_the_latest():
    df = _quiet_then([(100.0, 104.2, 99.9, 104.0), (104.0, 104.3, 103.8, 104.1)])
    assert detect_displacement(df) is None          # latest bar is quiet
    assert displacement_at(df, 20) == "bullish"     # the earlier impulse bar is still found
    assert displacement_at(df, 21) is None


def test_displacement_at_matches_detect_displacement_on_the_latest_bar():
    df = _quiet_then([(100.0, 100.1, 95.8, 96.0)])
    assert displacement_at(df, len(df) - 1) == detect_displacement(df) == "bearish"


def test_is_feed_stale_uses_the_newest_candle_time():
    from datetime import datetime, timedelta, timezone
    import config
    df = _quiet_then([])
    latest = df["time"].iloc[-1].to_pydatetime()
    limit = 5 * 60 + config.DATA_STALE_SECONDS
    assert is_feed_stale(df, latest + timedelta(seconds=limit)) is False
    assert is_feed_stale(df, latest + timedelta(seconds=limit + 1)) is True
    assert is_feed_stale(df.iloc[0:0], datetime.now(timezone.utc)) is True
