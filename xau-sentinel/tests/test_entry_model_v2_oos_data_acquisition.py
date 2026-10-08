"""Regression tests for research/entry_model_v2_oos/data_acquisition.py -- the fresh MT5 data
acquisition/append pipeline for a future Entry Model V2 OOS run. Tests the plumbing only: connection
failure handling, stale-data rejection, deduplication, timestamp/closed-candle handling, boundary
filtering, and contamination detection. No real MT5 connection is used here; real-connection
behaviour was verified manually against a live terminal while building this (see
docs/entry-model-v2-oos-data-acquisition.md).
"""
import time as time_mod

import pandas as pd
import pytest

import config
from mt5 import connection
from research.entry_model_v2_oos import data_acquisition as da, spec
from research.entry_model_v2_oos.boundary import (
    OOSBoundaryViolation,
    assert_raw_data_has_no_pre_boundary_contamination,
)

AFTER = spec.IS_DATA_END + pd.Timedelta(hours=1)


def _bars(times, minutes=5, closed=True):
    times = pd.DatetimeIndex(times)
    n = len(times)
    df = pd.DataFrame({
        "time": times, "open": [4100.0] * n, "high": [4101.0] * n, "low": [4099.0] * n,
        "close": [4100.5] * n, "volume": [100] * n,
    })
    df["close_time"] = df["time"] + pd.Timedelta(minutes=minutes)
    df["is_closed"] = closed
    return df


# --- ensure_live_connection: connection failure handling -------------------------------------------

def test_ensure_live_connection_raises_when_mode_is_not_live(monkeypatch):
    monkeypatch.setattr(config, "IS_LIVE", False)
    monkeypatch.setattr(config, "MODE", "mock")
    with pytest.raises(da.AcquisitionError, match="not 'live'"):
        da.ensure_live_connection()


def test_ensure_live_connection_raises_when_mt5_connect_fails(monkeypatch):
    monkeypatch.setattr(config, "IS_LIVE", True)
    monkeypatch.setattr(connection, "is_connected", lambda: False)
    monkeypatch.setattr(connection, "connect", lambda: False)
    monkeypatch.setattr(connection, "last_error", lambda: "MT5 initialize() failed: (1, 'fake')")
    with pytest.raises(da.AcquisitionError, match="MT5 connection failed"):
        da.ensure_live_connection()


def test_ensure_live_connection_raises_when_symbol_not_ready(monkeypatch):
    monkeypatch.setattr(config, "IS_LIVE", True)
    monkeypatch.setattr(connection, "is_connected", lambda: True)
    monkeypatch.setattr(connection, "symbol_ready", lambda: False)
    monkeypatch.setattr(connection, "last_error", lambda: "Symbol not found")
    with pytest.raises(da.AcquisitionError, match="not ready"):
        da.ensure_live_connection()


def test_ensure_live_connection_passes_silently_when_everything_is_ready(monkeypatch):
    monkeypatch.setattr(config, "IS_LIVE", True)
    monkeypatch.setattr(connection, "is_connected", lambda: True)
    monkeypatch.setattr(connection, "symbol_ready", lambda: True)
    da.ensure_live_connection()  # no exception


# --- fetch_fresh: stale-data rejection -------------------------------------------------------------

def test_fetch_fresh_raises_after_repeated_stale_reads(monkeypatch):
    monkeypatch.setattr(da, "ensure_live_connection", lambda: None)
    stale_time = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=1)
    stale_df = _bars([stale_time])
    monkeypatch.setattr(da.market_data, "get_candles", lambda tf, count: stale_df)
    monkeypatch.setattr(time_mod, "sleep", lambda s: None)
    with pytest.raises(da.AcquisitionError, match="stale"):
        da.fetch_fresh("M5", max_bars=10, max_sync_retries=2, retry_wait_seconds=0)


def test_fetch_fresh_succeeds_once_a_fresh_read_arrives(monkeypatch):
    monkeypatch.setattr(da, "ensure_live_connection", lambda: None)
    now = pd.Timestamp.now(tz="UTC")
    stale_df = _bars([now - pd.Timedelta(days=1)])
    fresh_df = _bars([now - pd.Timedelta(minutes=5)])
    calls = {"n": 0}

    def fake_get_candles(tf, count):
        calls["n"] += 1
        return stale_df if calls["n"] == 1 else fresh_df

    monkeypatch.setattr(da.market_data, "get_candles", fake_get_candles)
    monkeypatch.setattr(time_mod, "sleep", lambda s: None)
    result = da.fetch_fresh("M5", max_bars=10, max_sync_retries=3, retry_wait_seconds=0)
    assert result is fresh_df
    assert calls["n"] == 2


# --- fresh_since_boundary: boundary filtering + closed-only ----------------------------------------

def test_fresh_since_boundary_excludes_pre_boundary_and_forming_rows(monkeypatch):
    monkeypatch.setattr(da, "ensure_live_connection", lambda: None)
    before = spec.IS_DATA_END - pd.Timedelta(minutes=5)
    at_boundary = spec.IS_DATA_END
    after_closed = spec.IS_DATA_END + pd.Timedelta(minutes=5)
    after_forming = spec.IS_DATA_END + pd.Timedelta(minutes=10)
    df = pd.concat([
        _bars([before], closed=True), _bars([at_boundary], closed=True),
        _bars([after_closed], closed=True), _bars([after_forming], closed=False),
    ], ignore_index=True)
    df["close_time"] = pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=1)  # keep fetch_fresh's own freshness check happy
    monkeypatch.setattr(da.market_data, "get_candles", lambda tf, count: df)
    result = da.fresh_since_boundary("M5")
    assert list(result["time"]) == [after_closed]  # only strictly-after AND closed survives


# --- append_fresh: deduplication and integrity -----------------------------------------------------

def test_append_fresh_writes_new_rows_to_an_empty_store(tmp_path):
    new_df = _bars([AFTER, AFTER + pd.Timedelta(minutes=5)])
    result = da.append_fresh("M5", new_df, root=tmp_path)
    assert result["n_newly_added"] == 2
    assert result["n_duplicates_skipped"] == 0
    stored = da.load_store("M5", root=tmp_path)
    assert len(stored) == 2


def test_append_fresh_deduplicates_identical_rows_on_a_second_call(tmp_path):
    new_df = _bars([AFTER, AFTER + pd.Timedelta(minutes=5)])
    da.append_fresh("M5", new_df, root=tmp_path)
    result = da.append_fresh("M5", new_df, root=tmp_path)
    assert result["n_newly_added"] == 0
    assert result["n_duplicates_skipped"] == 2
    assert result["n_total_after"] == 2


def test_append_fresh_raises_on_a_genuine_ohlc_revision_not_a_normal_duplicate(tmp_path):
    first = _bars([AFTER])
    da.append_fresh("M5", first, root=tmp_path)
    revised = first.copy()
    revised["low"] = 4050.0  # a different value at the SAME timestamp -- a revision, not a dup
    with pytest.raises(da.AcquisitionError, match="revising its own history"):
        da.append_fresh("M5", revised, root=tmp_path)


def test_append_fresh_reports_unexpected_gaps_without_hiding_them(tmp_path):
    new_df = _bars([AFTER, AFTER + pd.Timedelta(hours=2)])  # a 2-hour gap on an M5 series
    result = da.append_fresh("M5", new_df, root=tmp_path)
    assert len(result["unexpected_gaps"]) == 1
    assert result["unexpected_gaps"][0]["width"] == "0 days 02:00:00"


def test_append_fresh_preserves_existing_data_across_calls_append_only(tmp_path):
    da.append_fresh("M5", _bars([AFTER]), root=tmp_path)
    da.append_fresh("M5", _bars([AFTER + pd.Timedelta(minutes=5)]), root=tmp_path)
    stored = da.load_store("M5", root=tmp_path)
    assert len(stored) == 2
    assert list(stored["time"]) == [AFTER, AFTER + pd.Timedelta(minutes=5)]


# --- timestamp normalization ------------------------------------------------------------------------

def test_stored_candles_keep_utc_aware_timestamps(tmp_path):
    da.append_fresh("M5", _bars([AFTER]), root=tmp_path)
    stored = da.load_store("M5", root=tmp_path)
    assert stored["time"].dt.tz is not None
    assert str(stored["time"].dt.tz) == "UTC"


# --- contamination / overlap detection (boundary.py) ------------------------------------------------

def test_contamination_check_passes_on_clean_post_boundary_data():
    raw = {"M5": _bars([AFTER, AFTER + pd.Timedelta(minutes=5)])}
    assert_raw_data_has_no_pre_boundary_contamination(raw)  # no exception


def test_contamination_check_raises_when_any_timeframe_has_a_pre_boundary_row():
    raw = {
        "M5": pd.concat([_bars([spec.IS_DATA_END - pd.Timedelta(minutes=5)]), _bars([AFTER])], ignore_index=True),
        "M1": _bars([AFTER], minutes=1),
    }
    with pytest.raises(OOSBoundaryViolation, match="M5"):
        assert_raw_data_has_no_pre_boundary_contamination(raw)


def test_contamination_check_flags_a_row_exactly_at_the_boundary_too():
    raw = {"M5": _bars([spec.IS_DATA_END])}
    with pytest.raises(OOSBoundaryViolation):
        assert_raw_data_has_no_pre_boundary_contamination(raw)


def test_contamination_check_ignores_timeframes_that_are_entirely_absent():
    raw = {"M5": _bars([AFTER]), "M1": None}
    assert_raw_data_has_no_pre_boundary_contamination(raw)  # no exception
