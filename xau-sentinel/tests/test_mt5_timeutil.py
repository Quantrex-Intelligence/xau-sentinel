"""Stage 19 tests for mt5/timeutil.py — the one explicit MT5-server-time
-> UTC conversion boundary (see docs/validation/ISSUE_LOG.md VAL-003).
Europe/Nicosia (the shipped FUNDEDNEXT_SERVER_TIMEZONE default) is UTC+2
in winter (EET) and UTC+3 in summer (EEST); both are exercised below to
also prove DST is handled via the timezone-aware conversion, not a fixed
offset.
"""
import calendar
from datetime import datetime, timezone

import pandas as pd
import pytest

import config
from mt5 import timeutil


def _server_epoch_for(server_wallclock: datetime) -> int:
    """What MT5's copy_rates_from_pos()/symbol_info_tick() would hand back
    for a given broker-server wall-clock reading: the epoch value you'd
    get if that reading were (incorrectly) treated as naive UTC."""
    return calendar.timegm(server_wallclock.timetuple())


@pytest.fixture(autouse=True)
def _fixed_server_timezone(monkeypatch):
    monkeypatch.setattr(config, "FUNDEDNEXT_SERVER_TIMEZONE", "Europe/Nicosia")


def test_to_utc_converts_a_winter_server_reading_correctly():
    # True UTC instant: 2026-01-15 12:00:00. Nicosia is UTC+2 in January,
    # so the server's own wall-clock reading at that instant is 14:00:00.
    raw_epoch = _server_epoch_for(datetime(2026, 1, 15, 14, 0, 0))
    result = timeutil.to_utc(raw_epoch)
    assert result == datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


def test_to_utc_converts_a_summer_dst_server_reading_correctly():
    # True UTC instant: 2026-07-15 12:00:00. Nicosia is UTC+3 (EEST) in July.
    raw_epoch = _server_epoch_for(datetime(2026, 7, 15, 15, 0, 0))
    result = timeutil.to_utc(raw_epoch)
    assert result == datetime(2026, 7, 15, 12, 0, 0, tzinfo=timezone.utc)


def test_series_to_utc_matches_scalar_to_utc_for_each_value():
    readings = [
        datetime(2026, 1, 15, 14, 0, 0),
        datetime(2026, 1, 15, 14, 5, 0),
        datetime(2026, 7, 15, 15, 0, 0),
    ]
    raw_epochs = pd.Series([_server_epoch_for(r) for r in readings])
    result = timeutil.series_to_utc(raw_epochs)

    for i, reading in enumerate(readings):
        expected = timeutil.to_utc(_server_epoch_for(reading))
        assert result.iloc[i].to_pydatetime() == expected


def test_naive_utc_misinterpretation_would_have_been_wrong_by_the_server_offset():
    """Proves the bug this fix closes: treating the raw epoch value as if
    it were already true UTC (the pre-Stage-19 behavior) is off by exactly
    the server's UTC offset — not a no-op, not a rounding error."""
    raw_epoch = _server_epoch_for(datetime(2026, 1, 15, 14, 0, 0))
    naive_utc_misread = datetime.fromtimestamp(raw_epoch, tz=timezone.utc)
    correct = timeutil.to_utc(raw_epoch)
    assert naive_utc_misread != correct
    assert (naive_utc_misread - correct).total_seconds() == 2 * 3600  # Nicosia is UTC+2 in January


def test_server_timezone_reads_the_configured_iana_zone():
    assert timeutil.server_timezone().key == "Europe/Nicosia"


def test_server_now_is_timezone_aware_in_the_configured_zone():
    now = timeutil.server_now()
    assert now.tzinfo is not None
    assert now.utcoffset() is not None
