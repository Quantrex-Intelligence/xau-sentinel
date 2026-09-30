"""Tests for ai/digest/store.py — duplicate prevention (INSERT OR IGNORE +
UNIQUE index) and last_sent() scoping."""
from datetime import date

import pytest

from ai.digest import store


@pytest.fixture(autouse=True)
def _init(temp_db):
    return temp_db


def test_record_sent_returns_true_on_first_insert():
    assert store.record_sent("WEEKLY", date(2026, 9, 21), date(2026, 9, 27), "telegram") is True


def test_record_sent_returns_false_on_a_duplicate_identity():
    store.record_sent("WEEKLY", date(2026, 9, 21), date(2026, 9, 27), "telegram")
    assert store.record_sent("WEEKLY", date(2026, 9, 21), date(2026, 9, 27), "telegram") is False


def test_was_sent_reflects_recorded_state():
    assert store.was_sent("WEEKLY", date(2026, 9, 21), date(2026, 9, 27), "telegram") is False
    store.record_sent("WEEKLY", date(2026, 9, 21), date(2026, 9, 27), "telegram")
    assert store.was_sent("WEEKLY", date(2026, 9, 21), date(2026, 9, 27), "telegram") is True


def test_different_periods_are_independent():
    store.record_sent("WEEKLY", date(2026, 9, 21), date(2026, 9, 27), "telegram")
    assert store.was_sent("WEEKLY", date(2026, 9, 28), date(2026, 10, 4), "telegram") is False


def test_different_digest_types_are_independent():
    store.record_sent("WEEKLY", date(2026, 9, 21), date(2026, 9, 27), "telegram")
    assert store.was_sent("MONTHLY", date(2026, 9, 21), date(2026, 9, 27), "telegram") is False


def test_different_channels_are_independent():
    store.record_sent("WEEKLY", date(2026, 9, 21), date(2026, 9, 27), "telegram")
    assert store.was_sent("WEEKLY", date(2026, 9, 21), date(2026, 9, 27), "mock") is False


def test_last_sent_returns_none_when_nothing_recorded():
    assert store.last_sent("WEEKLY") is None


def test_last_sent_returns_the_most_recent_period():
    store.record_sent("WEEKLY", date(2026, 9, 14), date(2026, 9, 20), "telegram")
    store.record_sent("WEEKLY", date(2026, 9, 21), date(2026, 9, 27), "telegram")
    result = store.last_sent("WEEKLY")
    assert result["period_start"] == "2026-09-21"
    assert result["period_end"] == "2026-09-27"
