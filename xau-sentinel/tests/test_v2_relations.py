"""Analysis V2 price-to-area relationships and the break/rejection/retest events."""
from datetime import datetime, timezone

import pandas as pd
import pytest

from analysis.v2.models import KeyArea
from analysis.v2.relations import classify_area

ATR = 1.0


def _area(low=3000.0, high=3002.0):
    return KeyArea(low, high, (), "RESISTANCE", "MODERATE", "test")


def _bars(rows):
    """rows: (open, high, low, close). Closed M5 bars, oldest first."""
    times = pd.date_range("2026-01-05 08:00", periods=len(rows), freq="5min", tz="UTC")
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df["time"] = times
    return df


def _quiet(n=10, level=2995.0):
    return [(level, level + 0.5, level - 0.5, level + 0.2)] * n


def test_inside_when_price_is_within_the_area():
    s = classify_area(_area(), _bars(_quiet()), 3001.0, ATR)
    assert s.relation == "INSIDE" and s.distance_atr == 0.0


def test_approaching_when_price_is_within_one_atr_below():
    s = classify_area(_area(), _bars(_quiet()), 2999.5, ATR)  # 0.5 ATR under the low edge
    assert s.relation == "APPROACHING"
    assert s.distance_atr == pytest.approx(0.5)


def test_below_when_price_is_further_than_one_atr_under_the_area():
    s = classify_area(_area(), _bars(_quiet()), 2997.0, ATR)  # 3 ATR under the low edge
    assert s.relation == "BELOW"
    assert s.distance_atr == pytest.approx(3.0)


def test_above_when_price_is_further_than_one_atr_over_the_area():
    s = classify_area(_area(), _bars(_quiet()), 3004.0, ATR)  # 2 ATR over the high edge
    assert s.relation == "ABOVE"
    assert s.distance_atr == pytest.approx(-2.0)


def test_breakout_up_is_reported_on_the_bar_that_crossed_and_price_is_still_above():
    rows = _quiet(10) + [(2999.5, 3000.0, 2999.0, 2999.8), (2999.8, 3003.5, 2999.7, 3003.2)]
    df = _bars(rows)
    s = classify_area(_area(), df, 3003.2, ATR)
    assert s.relation == "BROKEN"
    breakouts = [e for e in s.events if e.kind == "BREAKOUT"]
    assert len(breakouts) == 1
    assert breakouts[0].direction == "bullish"
    assert breakouts[0].time == df["time"].iloc[-1]


def test_a_close_inside_the_break_buffer_is_not_a_breakout():
    rows = _quiet(10) + [(2999.5, 3002.05, 2999.0, 3002.05)]  # 0.05 ATR past the high, less than the 0.1 buffer
    s = classify_area(_area(), _bars(rows), 3002.05, ATR)
    assert not [e for e in s.events if e.kind == "BREAKOUT"]
    assert s.relation == "APPROACHING"  # just outside the high edge, not broken


def test_failed_breakout_is_reported_when_price_closes_back_inside():
    rows = _quiet(10) + [(2999.5, 3003.5, 2999.0, 3003.2), (3003.2, 3003.4, 3001.0, 3001.2)]
    s = classify_area(_area(), _bars(rows), 3001.2, ATR)
    failed = [e for e in s.events if e.kind == "FAILED_BREAKOUT"]
    assert failed and failed[0].direction == "bearish"
    assert s.relation != "BROKEN"


def test_rejection_from_below_closes_under_the_area_and_is_rejecting():
    rows = _quiet(10) + [(2998.0, 3000.8, 2997.8, 2999.0)]  # opens below, wicks into 3000, closes below
    s = classify_area(_area(), _bars(rows), 2999.0, ATR)
    rejections = [e for e in s.events if e.kind == "REJECTION"]
    assert rejections and rejections[-1].direction == "bearish"
    assert s.relation == "REJECTING"


def test_retest_is_reported_when_price_returns_to_a_broken_edge_and_holds_above_it():
    rows = _quiet(10) + [(2999.5, 3003.5, 2999.0, 3003.2),
                         (3003.2, 3003.6, 3002.4, 3003.3),  # comes back within 0.5 ATR of 3002 and closes above
                         (3003.3, 3004.0, 3003.0, 3003.8)]
    s = classify_area(_area(), _bars(rows), 3003.8, ATR)
    retests = [e for e in s.events if e.kind == "RETEST"]
    assert retests and retests[-1].direction == "bullish"
    assert s.relation == "BROKEN"


@pytest.mark.parametrize("price,atr", [(None, 1.0), (3001.0, None), (3001.0, 0.0), (3001.0, float("nan"))])
def test_missing_price_or_atr_gives_unknown_not_a_guess(price, atr):
    s = classify_area(_area(), _bars(_quiet()), price, atr)
    assert s.relation == "UNKNOWN"
    assert s.distance_atr is None


def test_missing_bars_gives_unknown():
    assert classify_area(_area(), None, 3001.0, ATR).relation == "UNKNOWN"
    assert classify_area(_area(), _bars(_quiet(1)), 3001.0, ATR).relation == "UNKNOWN"


def test_inside_takes_priority_over_an_earlier_rejection():
    rows = _quiet(10) + [(2998.0, 3000.8, 2997.8, 2999.0), (2999.0, 3001.5, 2998.9, 3001.0)]
    s = classify_area(_area(), _bars(rows), 3001.0, ATR)
    assert any(e.kind == "REJECTION" for e in s.events)
    assert s.relation == "INSIDE"


def test_every_reason_is_explicit_text():
    s = classify_area(_area(), _bars(_quiet()), 2999.5, ATR)
    assert s.reasons and all(isinstance(r, str) and r for r in s.reasons)
