"""Stage 21 tests for candle-state (CLOSED vs FORMING) semantics — see
docs/validation/ISSUE_LOG.md VAL-006. A candle's state is always derived
from its own close_time against the authoritative current time, never
assumed from row position or count.
"""
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

import config
from mt5 import connection, market_data

_TIMEFRAMES = ["M5", "M15", "H1", "H4"]


def _single_candle_df(open_time: datetime) -> pd.DataFrame:
    return pd.DataFrame({
        "time": pd.to_datetime([open_time], utc=True),
        "open": [100.0], "high": [100.5], "low": [99.5], "close": [100.2], "volume": [10],
    })


# ---------------------------------------------------------------------------
# Core state derivation: _with_candle_state()
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("timeframe", _TIMEFRAMES)
def test_a_candle_whose_close_time_is_in_the_future_is_forming(timeframe):
    now = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
    open_time = now - timedelta(minutes=1)  # close_time = open_time + duration, always > now
    df = market_data._with_candle_state(_single_candle_df(open_time), timeframe, now=now)
    assert df["is_closed"].iloc[0] == False  # noqa: E712 -- explicit bool check reads clearer here


@pytest.mark.parametrize("timeframe", _TIMEFRAMES)
def test_a_candle_whose_close_time_has_passed_is_closed(timeframe):
    now = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
    minutes = market_data._TIMEFRAME_MINUTES[timeframe]
    open_time = now - timedelta(minutes=minutes * 3)  # closed well before now
    df = market_data._with_candle_state(_single_candle_df(open_time), timeframe, now=now)
    assert df["is_closed"].iloc[0] == True  # noqa: E712


@pytest.mark.parametrize("timeframe", _TIMEFRAMES)
def test_a_candle_exactly_at_the_close_boundary_is_deterministically_closed(timeframe):
    """close_time == now is the documented inclusive boundary choice —
    CLOSED, not FORMING."""
    now = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
    minutes = market_data._TIMEFRAME_MINUTES[timeframe]
    open_time = now - timedelta(minutes=minutes)  # close_time == now exactly
    df = market_data._with_candle_state(_single_candle_df(open_time), timeframe, now=now)
    assert df["close_time"].iloc[0] == now
    assert df["is_closed"].iloc[0] == True  # noqa: E712


def test_close_time_is_derived_from_open_time_plus_the_timeframes_own_duration():
    open_time = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
    df = market_data._with_candle_state(_single_candle_df(open_time), "H1", now=open_time)
    assert df["close_time"].iloc[0] == open_time + timedelta(minutes=60)


# ---------------------------------------------------------------------------
# Mock mode — deterministic, last candle always forming, every timeframe.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("timeframe", _TIMEFRAMES)
def test_mock_mode_last_candle_is_always_forming(monkeypatch, timeframe):
    monkeypatch.setattr(config, "IS_MOCK", True)
    df = market_data.get_candles(timeframe, count=20)
    assert df["is_closed"].iloc[-1] == False  # noqa: E712
    assert df["is_closed"].iloc[:-1].all()


def test_mock_mode_is_closed_column_is_deterministic_given_the_same_now(monkeypatch):
    monkeypatch.setattr(config, "IS_MOCK", True)
    fixed_now = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
    df1 = market_data._mock_candles("M5", 10)
    # Rebuild with an explicitly pinned `now` twice -- same input, same output.
    base = df1.drop(columns=["close_time", "is_closed"])
    a = market_data._with_candle_state(base, "M5", now=fixed_now)
    b = market_data._with_candle_state(base, "M5", now=fixed_now)
    pd.testing.assert_series_equal(a["is_closed"], b["is_closed"])
    pd.testing.assert_series_equal(a["close_time"], b["close_time"])


# ---------------------------------------------------------------------------
# Live mode — via a FakeMT5, mirroring tests/test_market_data.py's own
# established convention (Stage 19).
# ---------------------------------------------------------------------------

def test_live_mode_candle_state_derived_from_real_timestamps_not_position(monkeypatch):
    import calendar
    monkeypatch.setattr(config, "FUNDEDNEXT_SERVER_TIMEZONE", "UTC")
    monkeypatch.setattr(config, "IS_MOCK", False)
    monkeypatch.setattr(config, "TRADING_SYMBOL", "XAUUSD")

    now = datetime.now(timezone.utc)
    # Bar 0 (oldest, first returned by MT5's pos=0-based fetch in this
    # fake) is well closed; bar 1 (most recent) is still forming.
    closed_open = now - timedelta(minutes=15)
    forming_open = now - timedelta(minutes=1)

    class FakeMT5:
        TIMEFRAME_M5 = 5

        def copy_rates_from_pos(self, symbol, timeframe, pos, count):
            return [
                {"time": calendar.timegm(closed_open.timetuple()), "open": 3700.0, "high": 3701.0,
                 "low": 3699.0, "close": 3700.5, "tick_volume": 100},
                {"time": calendar.timegm(forming_open.timetuple()), "open": 3700.5, "high": 3702.0,
                 "low": 3700.0, "close": 3701.5, "tick_volume": 40},
            ]

    monkeypatch.setattr(market_data, "mt5", FakeMT5())
    monkeypatch.setattr(connection, "is_connected", lambda: True)

    df = market_data.get_candles("M5", count=2)
    assert df["is_closed"].iloc[0] == True  # noqa: E712
    assert df["is_closed"].iloc[1] == False  # noqa: E712
