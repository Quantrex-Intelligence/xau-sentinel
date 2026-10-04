"""Analysis V2 event detection: each event is tied to the closed bar where it first
appears, and BOS/MSS are replayed from the existing structure logic."""
import numpy as np
import pandas as pd
import pytest

from analysis.structure import analyze_structure, displacement_at, compute_atr
from analysis.v2.events import (
    momentum_loss_event, pullback_event, range_events, structure_transitions,
    displacement_events, volatility_events,
)
from tests.v2_fixtures import trend_set
from tests.test_structure import _flat_candles_from_path, _ramp_path


def _ohlc(rows, start="2026-01-05 00:00"):
    times = pd.date_range(start, periods=len(rows), freq="5min", tz="UTC")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df["time"] = times
    df["volume"] = 100.0
    return df


def test_bos_events_occur_exactly_on_the_bar_where_the_structure_state_flips():
    """Property: at each reported BOS bar the existing analysis shows the break,
    and the bar before it did not. Replaying the state, not restating it."""
    h1 = trend_set("up")["H1"]
    from analysis.structure import closed_only
    closed = closed_only({"H1": h1})["H1"]
    events = structure_transitions(closed, "H1", window=len(closed) - 20)
    bos = [e for e in events if e.kind == "BOS"]
    assert bos, "the trending fixture must produce at least one BOS, or this test is vacuous"
    for e in bos:
        i = int(closed.index[closed["time"] == e.time][0])
        assert analyze_structure(closed.iloc[: i + 1]).last_bos == e.direction
        assert analyze_structure(closed.iloc[:i]).last_bos != e.direction


def test_event_is_reported_once_not_on_every_later_bar():
    h1 = trend_set("up")["H1"]
    from analysis.structure import closed_only
    closed = closed_only({"H1": h1})["H1"]
    events = [e for e in structure_transitions(closed, "H1", window=len(closed) - 20) if e.kind == "BOS"]
    times = [e.time for e in events]
    assert len(times) == len(set(times))


def test_structure_events_need_enough_history_and_return_empty_otherwise():
    assert structure_transitions(None, "H1", 12) == []
    short = _ohlc([(100, 101, 99, 100)] * 5)
    assert structure_transitions(short, "H1", 12) == []


def test_momentum_loss_fires_when_recent_bodies_shrink_after_a_one_way_run():
    rows = [(100 + i, 101 + i, 99 + i, 100.9 + i) for i in range(6)]  # six bullish bodies of +0.9
    rows += [(105.0, 105.1, 104.95, 105.05)] * 3  # tiny bodies
    event = momentum_loss_event(_ohlc(rows))
    assert event is not None and event.kind == "MOMENTUM_LOSS" and event.direction == "bullish"


def test_momentum_loss_does_not_fire_when_earlier_bodies_were_mixed():
    rows = [(100, 101, 99, 100.9), (101, 102, 100, 100.2), (100.2, 101, 99.5, 100.8),
            (100.8, 101, 100, 100.1), (100.1, 101, 99, 100.6), (100.6, 101, 100, 100.55),
            (100.55, 100.6, 100.5, 100.56), (100.56, 100.6, 100.5, 100.55), (100.55, 100.6, 100.5, 100.56)]
    assert momentum_loss_event(_ohlc(rows)) is None


def test_pullback_reports_the_retracement_of_the_latest_leg():
    # 80 -> 120 -> 100: the last close retraces exactly 50% of the 80-120 leg.
    path = _ramp_path([100, 80, 120, 100], steps_per_leg=12)
    frame = _flat_candles_from_path(path)
    from analysis.structure import closed_only
    closed = closed_only({"H1": frame})["H1"]
    event = pullback_event(closed, "H1")
    assert event is not None
    assert event.kind == "PULLBACK" and event.direction == "bearish"
    assert "50%" in event.detail


def test_compression_fires_when_recent_ranges_collapse_below_atr():
    normal = [(100.0, 101.0, 99.0, 100.5)] * 40  # range 2.0 each
    tight = [(100.5, 100.55, 100.45, 100.5)] * 6  # range 0.1 each
    events = range_events(_ohlc(normal + tight), window=10)
    assert any(e.kind == "COMPRESSION" for e in events)


def test_range_expansion_fires_on_a_bar_far_above_the_prior_mean_range():
    flat = [(100.0, 100.5, 99.5, 100.2)] * 45
    burst = [(100.2, 110.0, 99.0, 109.5)]
    events = range_events(_ohlc(flat + burst), window=5)
    expansions = [e for e in events if e.kind == "RANGE_EXPANSION"]
    assert expansions and expansions[-1].direction == "bullish"


def test_volatility_expansion_is_reported_when_the_atr_ratio_crosses_up():
    quiet = [(100.0, 100.25, 99.75, 100.0)] * 35
    loud = []
    price = 100.0
    for i in range(30):
        step = 3.0 if i % 2 == 0 else -3.0
        loud.append((price, price + 3.0, price - 3.0, price + step * 0.2))
        price += step * 0.2
    events = volatility_events(_ohlc(quiet + loud), window=30)
    assert any(e.kind == "VOLATILITY_EXPANSION" for e in events)


def test_displacement_events_match_the_existing_displacement_rule():
    rows = [(100.0 + 0.05 * (i % 3), 100.5 + 0.05 * (i % 3), 99.5, 100.1 + 0.05 * (i % 3)) for i in range(40)]
    rows.append((100.1, 110.0, 100.0, 109.8))  # large bullish body
    df = _ohlc(rows)
    events = displacement_events(df, window=5)
    last = len(df) - 1
    atr = compute_atr(df)
    assert displacement_at(df, last, atr=atr) == "bullish"
    assert any(e.time == df["time"].iloc[last] and e.direction == "bullish" for e in events)


@pytest.mark.parametrize("n", [0, 1, 3])
def test_event_functions_handle_tiny_inputs_without_error(n):
    df = _ohlc([(100, 101, 99, 100)] * n) if n else None
    assert displacement_events(df) == []
    assert volatility_events(df) == []
    assert range_events(df) == []
    assert momentum_loss_event(df) is None
    assert pullback_event(df, "H1") is None
