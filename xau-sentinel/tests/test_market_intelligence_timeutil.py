"""Tests for parse_timestamp(): the "critical" safety requirement is that
every parsed value is timezone-aware UTC, never naive, and unparseable
input degrades to None rather than raising or guessing."""
from datetime import datetime, timezone

from ai.market_intelligence.providers.timeutil import parse_timestamp


def test_none_and_empty_string_return_none():
    assert parse_timestamp(None) is None
    assert parse_timestamp("") is None


def test_unparseable_string_returns_none_not_a_raise():
    assert parse_timestamp("not a date at all") is None


def test_epoch_int_parses_to_aware_utc_datetime():
    result = parse_timestamp(1700000000)
    assert result is not None
    assert result.tzinfo is not None
    assert result == datetime.fromtimestamp(1700000000, tz=timezone.utc)


def test_epoch_float_parses_to_aware_utc_datetime():
    result = parse_timestamp(1700000000.5)
    assert result is not None
    assert result.tzinfo is not None


def test_rfc822_pubdate_parses_to_aware_utc_datetime():
    result = parse_timestamp("Mon, 28 Sep 2026 14:12:00 GMT")
    assert result is not None
    assert result.tzinfo is not None
    assert result.year == 2026 and result.month == 9 and result.day == 28


def test_iso8601_with_z_suffix_parses_to_aware_utc_datetime():
    result = parse_timestamp("2026-09-28T14:12:00Z")
    assert result is not None
    assert result.tzinfo is not None
    assert result.utcoffset().total_seconds() == 0


def test_iso8601_with_explicit_offset_stays_aware():
    result = parse_timestamp("2026-09-28T14:12:00+05:00")
    assert result is not None
    assert result.tzinfo is not None


def test_date_only_string_is_assumed_utc_and_never_naive():
    result = parse_timestamp("2026-09-28")
    assert result is not None
    assert result.tzinfo is not None


def test_result_is_never_naive_across_all_valid_forms():
    for value in (1700000000, "Mon, 28 Sep 2026 14:12:00 GMT", "2026-09-28T14:12:00Z", "2026-09-28"):
        result = parse_timestamp(value)
        assert result is not None
        assert result.tzinfo is not None, f"{value!r} produced a naive datetime"


def test_out_of_range_epoch_returns_none_not_a_raise():
    assert parse_timestamp(99999999999999999) is None
