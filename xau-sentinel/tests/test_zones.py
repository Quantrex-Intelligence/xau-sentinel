"""Key zone validation: PDH/PDL, session highs/lows, swing levels, VWAP."""
from datetime import datetime, timezone

from analysis.zones import compute_zones, compute_session_vwap, current_session
from tests.conftest import make_candles


def _day_of_m5_candles(day, base=100.0):
    """24h of M5 candles for a given UTC date, with a distinct, identifiable
    high/low in each session window so zone detection can be checked exactly."""
    rows = []
    start = datetime(day.year, day.month, day.day, 0, 0, tzinfo=timezone.utc)
    for i in range(288):  # 24h * 12 bars/hour
        hour = (i * 5 // 60) % 24
        # Distinct, non-overlapping price bands per session for unambiguous assertions.
        if 0 <= hour < 6:  # Asian
            band = base + 5
        elif 7 <= hour < 12:  # London
            band = base + 10
        elif 12 <= hour < 20:  # NY
            band = base + 15
        else:
            band = base
        o = c = band
        h = band + 0.5
        l = band - 0.5
        rows.append((o, h, l, c))
    return make_candles(rows, tf_minutes=5, start=start)


def _day_of_h1_candles(day, base=100.0, hours=range(24)):
    """H1 candles for a UTC date, using the same session bands as the M5
    helper above (so the H1 day range equals the M5 day range)."""
    import pandas as pd
    frames = []
    for hour in hours:
        if 0 <= hour < 6:
            band = base + 5
        elif 7 <= hour < 12:
            band = base + 10
        elif 12 <= hour < 20:
            band = base + 15
        else:
            band = base
        start = datetime(day.year, day.month, day.day, hour, 0, tzinfo=timezone.utc)
        frames.append(make_candles([(band, band + 0.5, band - 0.5, band)], tf_minutes=60, start=start))
    return pd.concat(frames, ignore_index=True)


def test_previous_and_current_day_high_low():
    day1 = _day_of_m5_candles(datetime(2026, 1, 5), base=100)
    day2 = _day_of_m5_candles(datetime(2026, 1, 6), base=200)
    import pandas as pd
    m5 = pd.concat([day1, day2], ignore_index=True)
    h1 = pd.concat([_day_of_h1_candles(datetime(2026, 1, 5), base=100),
                    _day_of_h1_candles(datetime(2026, 1, 6), base=200)], ignore_index=True)

    zones = compute_zones(m5, h1=h1, h4=None)
    assert zones["Previous Day High"] == round(100 + 15 + 0.5, 2)
    assert zones["Previous Day Low"] == round(100 - 0.5, 2)
    assert zones["Current Day High"] == round(200 + 15 + 0.5, 2)
    assert zones["Current Day Low"] == round(200 - 0.5, 2)


def test_session_highs_and_lows_are_independent_bands():
    day = _day_of_m5_candles(datetime(2026, 1, 5), base=100)
    zones = compute_zones(day, h1=None, h4=None)
    assert zones["Asian High"] == 105.5
    assert zones["Asian Low"] == 104.5
    assert zones["London High"] == 110.5
    assert zones["London Low"] == 109.5


def test_h1_and_h4_swing_levels_use_higher_timeframe_data():
    # A clean zigzag on H1/H4 so find_swing_points has an unambiguous last swing.
    from tests.test_structure import _ramp_path, _flat_candles_from_path, BULLISH_POINTS
    h1 = _flat_candles_from_path(_ramp_path(BULLISH_POINTS[:6], steps_per_leg=7), tail=[113, 114, 115])
    h4 = _flat_candles_from_path(_ramp_path(BULLISH_POINTS[:6], steps_per_leg=7), tail=[113, 114, 115])
    m5 = make_candles([(100, 100.5, 99.5, 100)])

    zones = compute_zones(m5, h1, h4)
    assert zones["H1 Swing High"] == 120.0
    assert zones["H1 Swing Low"] == 112.0
    assert zones["H4 Swing High"] == 120.0
    assert zones["H4 Swing Low"] == 112.0


def test_vwap_is_volume_weighted_not_a_simple_average():
    df = make_candles([
        (100, 101, 99, 100, 1000),   # typical=100, heavy volume
        (110, 111, 109, 110, 10),    # typical=110, tiny volume
    ])
    vwap = compute_session_vwap(df)
    # Dominated by the heavy-volume bar, must sit close to 100, far from the naive average (105).
    assert 100.0 <= vwap < 101.0


def test_vwap_handles_zero_volume_without_crashing():
    df = make_candles([(100, 101, 99, 100, 0), (100, 101, 99, 100, 0)])
    vwap = compute_session_vwap(df)
    assert vwap is not None  # zero volume is replaced with 1, so this still degrades to a plain average


def test_current_session_labels_match_configured_windows():
    assert current_session(datetime(2026, 1, 5, 2, 0, tzinfo=timezone.utc)) == "Asian"
    assert current_session(datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)) == "London"
    assert current_session(datetime(2026, 1, 5, 14, 0, tzinfo=timezone.utc)) == "New York"
    assert current_session(datetime(2026, 1, 5, 22, 0, tzinfo=timezone.utc)) == "Off-session"


def test_empty_m5_yields_no_zones_without_crashing():
    assert compute_zones(None, None, None) == {}
    import pandas as pd
    assert compute_zones(pd.DataFrame(), None, None) == {}


# --- Stage 23A: VAL-007 / VAL-015 --------------------------------------------

def test_previous_day_uses_full_prior_day_even_when_m5_window_covers_only_its_last_hours():
    """VAL-007: 300 M5 bars at 01:00 reach back only to ~00:00 the previous
    day's evening. The prior day's NY-session high (115.5) sits outside that
    M5 window, but H1 still covers it, so Previous Day High is the true one."""
    import pandas as pd
    yesterday_evening = _day_of_m5_candles(datetime(2026, 1, 6), base=100).iloc[-36:]  # 21:00-23:55 only
    today_m5 = _day_of_m5_candles(datetime(2026, 1, 7), base=200).iloc[:12]
    m5 = pd.concat([yesterday_evening, today_m5], ignore_index=True)
    h1 = pd.concat([_day_of_h1_candles(datetime(2026, 1, 6), base=100),
                    _day_of_h1_candles(datetime(2026, 1, 7), base=200, hours=range(1))], ignore_index=True)

    assert float(yesterday_evening["high"].max()) == 100.5  # M5 alone would have understated it
    zones = compute_zones(m5, h1=h1, h4=None)
    assert zones["Previous Day High"] == 115.5
    assert zones["Previous Day Low"] == 99.5


def test_previous_day_on_monday_is_friday_not_sunday_stub():
    """VAL-015: 2026-01-12 is a Monday; Sunday 2026-01-11 has only a 22:00-23:00
    re-open stub and must be skipped in favour of Friday 2026-01-09."""
    import pandas as pd
    friday = _day_of_h1_candles(datetime(2026, 1, 9), base=100)
    sunday_stub = _day_of_h1_candles(datetime(2026, 1, 11), base=300, hours=range(22, 24))
    monday_h1 = _day_of_h1_candles(datetime(2026, 1, 12), base=200, hours=range(3))
    h1 = pd.concat([friday, sunday_stub, monday_h1], ignore_index=True)
    m5 = _day_of_m5_candles(datetime(2026, 1, 12), base=200).iloc[:36]

    zones = compute_zones(m5, h1=h1, h4=None)
    assert zones["Previous Day High"] == 115.5
    assert zones["Previous Day Low"] == 99.5


def test_no_previous_day_zone_without_prior_weekday_history():
    m5 = _day_of_m5_candles(datetime(2026, 1, 5), base=100)
    h1 = _day_of_h1_candles(datetime(2026, 1, 5), base=100)
    zones = compute_zones(m5, h1=h1, h4=None)
    assert "Previous Day High" not in zones and "Previous Day Low" not in zones
