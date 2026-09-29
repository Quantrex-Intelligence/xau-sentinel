"""Liquidity validation: sweeps must require a buffer-beyond-level *and* a
close back on the other side — not every wick that grazes a level."""
from analysis.liquidity import detect_sweeps, detect_equal_levels
from tests.conftest import make_candles


def _base_candles(n=10, price=100.0):
    return make_candles([(price, price + 0.2, price - 0.2, price) for _ in range(n)])


def test_genuine_sweep_of_previous_day_high_is_detected():
    zones = {"Previous Day High": 105.0}
    df = _base_candles()
    sweep_bar = make_candles([(104.8, 105.6, 104.7, 104.9)])  # high beyond level+buffer, closes back under it
    import pandas as pd
    df = pd.concat([df, sweep_bar], ignore_index=True)

    events = detect_sweeps(df, zones, buffer=0.5)
    assert len(events) == 1
    assert events[0].label == "Previous Day High swept"
    assert events[0].kind == "sweep_high"


def test_wick_within_buffer_does_not_qualify_as_sweep():
    zones = {"Previous Day High": 105.0}
    df = _base_candles()
    small_wick = make_candles([(104.8, 105.2, 104.7, 104.9)])  # high only 0.2 beyond level, buffer requires 0.5
    import pandas as pd
    df = pd.concat([df, small_wick], ignore_index=True)

    events = detect_sweeps(df, zones, buffer=0.5)
    assert events == []


def test_breakout_that_continues_is_not_a_sweep():
    """Price trades beyond the level and CLOSES beyond it too (a breakout,
    not a sweep-and-reject) — must not be flagged as a liquidity sweep."""
    zones = {"Previous Day High": 105.0}
    df = _base_candles()
    breakout_bar = make_candles([(104.8, 106.0, 104.7, 105.8)])  # closes above the level, not back under it
    import pandas as pd
    df = pd.concat([df, breakout_bar], ignore_index=True)

    events = detect_sweeps(df, zones, buffer=0.5)
    assert events == []


def test_sweep_followed_by_rejection_flags_once():
    zones = {"Previous Day Low": 95.0}
    df = _base_candles()
    reject_bar = make_candles([(95.2, 95.3, 94.4, 95.1)])  # sweeps below 95 - buffer, closes back above
    import pandas as pd
    df = pd.concat([df, reject_bar], ignore_index=True)

    events = detect_sweeps(df, zones, buffer=0.5)
    assert len(events) == 1
    assert events[0].kind == "sweep_low"


def test_only_first_qualifying_bar_per_level_counts():
    """Once a level has been swept-and-rejected, further bars repeating the
    same pattern are continuation, not a fresh liquidity event."""
    zones = {"Previous Day High": 105.0}
    df = _base_candles()
    repeats = make_candles([
        (104.8, 105.6, 104.7, 104.9),
        (104.8, 105.7, 104.7, 104.9),
        (104.8, 105.8, 104.7, 104.9),
    ])
    import pandas as pd
    df = pd.concat([df, repeats], ignore_index=True)

    events = detect_sweeps(df, zones, buffer=0.5)
    assert len(events) == 1


def test_sweep_without_confirmation_close_still_beyond_level():
    """A bar that pierces the level but never closes back is a break, not a
    confirmed sweep-and-reject — must not be flagged."""
    zones = {"Previous Day High": 105.0}
    df = _base_candles()
    no_confirm = make_candles([(104.8, 105.9, 105.1, 105.5)])  # low itself stays above the level -> no rejection
    import pandas as pd
    df = pd.concat([df, no_confirm], ignore_index=True)

    events = detect_sweeps(df, zones, buffer=0.5)
    assert events == []


def test_equal_highs_detected_within_tolerance():
    from tests.test_structure import _ramp_path, _flat_candles_from_path
    # Two highs at ~120 separated by a low, within EQUAL_LEVEL_TOLERANCE(0.5).
    path = _ramp_path([100, 90, 120.2, 95, 119.9], steps_per_leg=7)
    df = _flat_candles_from_path(path, tail=[118, 117, 116])
    events = detect_equal_levels(df, tolerance=0.5)
    equal_highs = [e for e in events if e.kind == "equal_high"]
    assert len(equal_highs) == 1


def test_equal_highs_not_flagged_when_outside_tolerance():
    from tests.test_structure import _ramp_path, _flat_candles_from_path
    path = _ramp_path([100, 90, 130, 95, 119.9], steps_per_leg=7)  # far apart: 130 vs 119.9
    df = _flat_candles_from_path(path, tail=[118, 117, 116])
    events = detect_equal_levels(df, tolerance=0.5)
    equal_highs = [e for e in events if e.kind == "equal_high"]
    assert equal_highs == []


def test_equal_lows_detected_within_tolerance():
    from tests.test_structure import _ramp_path, _flat_candles_from_path
    path = _ramp_path([120, 100.2, 110, 99.9, 108], steps_per_leg=7)
    df = _flat_candles_from_path(path, tail=[109, 110, 111])
    events = detect_equal_levels(df, tolerance=0.5)
    equal_lows = [e for e in events if e.kind == "equal_low"]
    assert len(equal_lows) == 1


def test_equal_lows_not_flagged_when_outside_tolerance():
    from tests.test_structure import _ramp_path, _flat_candles_from_path
    path = _ramp_path([120, 100.2, 110, 80, 108], steps_per_leg=7)  # far apart: 100.2 vs 80
    df = _flat_candles_from_path(path, tail=[109, 110, 111])
    events = detect_equal_levels(df, tolerance=0.5)
    equal_lows = [e for e in events if e.kind == "equal_low"]
    assert equal_lows == []


def test_equal_level_detection_does_not_create_a_liquidity_sweep():
    """Equal highs/lows are a distinct concept from a sweep (price trading
    through a level and rejecting) — detect_equal_levels must never itself
    register a sweep_high/sweep_low event."""
    from tests.test_structure import _ramp_path, _flat_candles_from_path
    path = _ramp_path([100, 90, 120.2, 95, 119.9], steps_per_leg=7)
    df = _flat_candles_from_path(path, tail=[118, 117, 116])
    events = detect_equal_levels(df, tolerance=0.5)
    assert all(e.kind in ("equal_high", "equal_low") for e in events)
    assert not any(e.kind in ("sweep_high", "sweep_low") for e in events)


def test_no_zones_means_no_sweeps():
    df = _base_candles()
    assert detect_sweeps(df, {}) == []


def test_empty_dataframe_does_not_crash():
    import pandas as pd
    assert detect_sweeps(pd.DataFrame(), {"Previous Day High": 105.0}) == []


def test_equal_level_detection_does_not_use_future_information():
    """Look-ahead audit: detect_equal_levels is built on find_swing_points,
    which is already proven non-repainting — confirm that holds through the
    equal-level layer too, using only already-matured swings."""
    from tests.test_structure import _ramp_path, _flat_candles_from_path
    path = _ramp_path([100, 90, 120.2, 95, 119.9, 90.1], steps_per_leg=7)
    df = _flat_candles_from_path(path, tail=[91, 92, 93])
    full = detect_equal_levels(df, tolerance=0.5)

    # A prefix that only has the first equal-high pair matured must already
    # report it, and must not change once more (still-future, at that point)
    # data is appended.
    prefix_cutoff = 32  # matures the first two highs (120.2, 119.9) only
    prefix = df.iloc[:prefix_cutoff]
    partial = detect_equal_levels(prefix, tolerance=0.5)
    equal_highs_partial = [e for e in partial if e.kind == "equal_high"]
    equal_highs_full_matured_at_cutoff = [
        e for e in full if e.kind == "equal_high" and e.time <= prefix["time"].iloc[-1]
    ]
    assert [(e.time, round(e.level_price, 1)) for e in equal_highs_partial] == \
           [(e.time, round(e.level_price, 1)) for e in equal_highs_full_matured_at_cutoff]


# --- Stage 23A: VAL-014 — session levels exclude the bar under test ---------

def _asian_session_with(extra_rows):
    """Bars from 00:00 UTC (inside the default 00-06 Asian session): ten quiet
    bars whose lows sit at 99.8, then `extra_rows`."""
    rows = [(100.0, 100.2, 99.8, 100.0) for _ in range(10)] + list(extra_rows)
    return make_candles(rows)


def test_in_session_sweep_of_the_sessions_own_prior_low_registers():
    """The sweep bar itself makes the new Asian low, so the full-session
    Asian Low (99.0) includes it. Measured against the full session, the bar can
    never sweep it. Measured against the bars before it (99.8), it does."""
    from analysis.zones import compute_zones
    df = _asian_session_with([(100.0, 100.1, 99.0, 100.0)])  # 0.8 through 99.8, closes back above
    zones = compute_zones(df, None, None)
    assert zones["Asian Low"] == 99.0

    events = [e for e in detect_sweeps(df, zones) if e.level_name == "Asian Low"]
    assert len(events) == 1
    assert events[0].kind == "sweep_low"
    assert events[0].level_price == 99.8  # the level actually swept, not the post-sweep extreme
    assert events[0].time == df["time"].iloc[10]


def test_earlier_session_sweep_does_not_vanish_when_a_later_bar_extends_the_extreme():
    from analysis.zones import compute_zones
    df = _asian_session_with([
        (100.0, 100.1, 99.0, 100.0),   # genuine sweep of 99.8
        (100.0, 100.1, 99.9, 100.0),
        (99.5, 99.6, 98.0, 98.2),      # later breakdown extends the low to 98.0, closes below
    ])
    zones = compute_zones(df, None, None)
    assert zones["Asian Low"] == 98.0

    events = [e for e in detect_sweeps(df, zones) if e.level_name == "Asian Low"]
    assert [e.time for e in events] == [df["time"].iloc[10]]
