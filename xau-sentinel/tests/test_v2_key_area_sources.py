"""Analysis V2 key-area sources added in increment 4: consolidation, rejection
areas, supply/demand origins, broken swings, week-to-date levels and justified
round-number levels. Each source is tested on a synthetic case it should and
should not fire on, and provenance is checked end to end."""
import pandas as pd

from analysis.structure import SwingPoint
from analysis.v2 import key_areas as ka


def _frame(rows, start="2026-01-05 00:00", freq="5min"):
    times = pd.date_range(start, periods=len(rows), freq=freq, tz="UTC")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df["time"] = times
    df["volume"] = 100.0
    return df


def _kinds(comps):
    return {c.evidence.kind for c in comps}


def _m5_quiet(n=80, level=3000.0):
    return _frame([(level, level + 0.5, level - 0.5, level + 0.1)] * n)


def test_consolidation_appears_only_for_a_tight_h1_range():
    h1_tight = _frame([(100, 101, 99, 100.5)] * 60 + [(100, 100.5, 99.5, 100)] * 12, freq="1h")
    h1_wide = _frame([(100, 101, 99, 100.5)] * 60 + [(100, 130, 70, 100)] * 12, freq="1h")
    tight = ka._extra_components(_m5_quiet(), h1_tight, None)
    wide = ka._extra_components(_m5_quiet(), h1_wide, None)
    assert {"CONSOLIDATION_HIGH", "CONSOLIDATION_LOW"} <= _kinds(tight)
    assert "CONSOLIDATION_HIGH" not in _kinds(wide)


def test_rejection_area_comes_from_a_long_wick_that_closed_back():
    rows = [(3000, 3000.5, 2999.5, 3000.1)] * 60
    rows.append((3000.1, 3010.0, 2999.9, 3000.2))  # long upper wick, body near the bottom
    comps = ka._extra_components(_frame(rows), None, None)
    rejections = [c for c in comps if c.evidence.kind == "REJECTION_HIGH"]
    assert rejections and rejections[-1].price == 3010.0


def test_no_rejection_area_for_a_plain_candle():
    rows = [(3000, 3000.5, 2999.5, 3000.1)] * 61
    comps = ka._extra_components(_frame(rows), None, None)
    assert "REJECTION_HIGH" not in _kinds(comps)


def test_demand_zone_is_the_last_bearish_bar_before_an_upward_displacement():
    base = [(100, 100.5, 99.5, 100.1)] * 60
    origin = [(100.4, 100.5, 99.2, 99.3)]  # last down-close bar, low 99.2, high 100.5
    thrust = [(99.3, 104.0, 99.2, 103.8)]  # large bullish body from the H1 origin
    h1 = _frame(base + origin + thrust + [(103.8, 104.0, 103.5, 103.9)] * 2, freq="1h")
    comps = ka._extra_components(_m5_quiet(), h1, None)
    demand = sorted(c.price for c in comps if c.evidence.kind == "DEMAND_ZONE")
    assert demand == [99.2, 100.5]


def test_broken_h1_swing_high_is_kept_as_a_reference(monkeypatch):
    h1 = _frame([(100, 101, 99, 100.5)] * 30 + [(100.5, 106.0, 100.4, 105.5)] * 3, freq="1h")
    fake = [SwingPoint(5, h1["time"].iloc[5], 101.0, "high"), SwingPoint(6, h1["time"].iloc[6], 99.0, "low")]
    monkeypatch.setattr(ka, "find_swing_points", lambda df, lookback=None: fake)
    comps = ka._extra_components(_m5_quiet(), h1, None)
    broken = [c for c in comps if c.evidence.kind == "H1_BROKEN_HIGH"]
    assert broken and broken[0].price == 101.0


def test_week_levels_only_when_history_covers_monday():
    monday = "2026-10-05 00:00"  # a Monday in UTC
    covered = _frame([(100, 101, 99, 100.5)] * 40, start="2026-10-04 12:00", freq="1h")
    partial = _frame([(100, 101, 99, 100.5)] * 40, start="2026-10-06 00:00", freq="1h")
    m5 = _frame([(100, 101, 99, 100.5)] * 80, start="2026-10-07 10:00")
    assert {"WEEK_HIGH", "WEEK_LOW"} <= _kinds(ka._extra_components(m5, covered, None))
    assert "WEEK_HIGH" not in _kinds(ka._extra_components(m5, partial, None))


def test_psychological_level_needs_repeated_touches_and_proximity():
    touches = [(3000.0, 3000.4, 2999.8, 3000.1)] * 3 + [(3000.0, 3000.2, 2999.5, 3000.0)] * 2
    filler = [(3003.0, 3003.4, 3002.6, 3003.1)] * 45
    h1 = _frame(touches + filler, freq="1h")
    m5 = _frame([(3000.0, 3000.5, 2999.5, 3000.2)] * 80)
    with_touches = ka._extra_components(m5, h1, None)
    assert any(c.evidence.kind == "PSYCH_LEVEL" and c.price == 3000.0 for c in with_touches)

    single = _frame([(3000.0, 3000.4, 2999.8, 3000.1)] + filler + [(3003.0, 3003.4, 3002.6, 3003.1)] * 4, freq="1h")
    assert "PSYCH_LEVEL" not in _kinds(ka._extra_components(m5, single, None))


def test_every_source_keeps_provenance_and_timeframe():
    h1 = _frame([(100, 101, 99, 100.5)] * 60 + [(100, 100.5, 99.5, 100)] * 12, freq="1h")
    m5 = _m5_quiet()
    comps = ka._extra_components(m5, h1, None)
    assert comps, "the fixture must produce at least one extra source, or this test is vacuous"
    for c in comps:
        assert c.evidence.source == "analysis.v2.key_areas"
        assert c.evidence.timeframe in {"M5", "H1"}
        assert c.evidence.note


def test_nothing_is_added_without_data():
    assert ka._extra_components(None, None, None) == []
    assert ka._extra_components(_frame([(1, 1, 1, 1)]), None, None) == []
