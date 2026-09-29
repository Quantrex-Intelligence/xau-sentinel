"""Tests for ai/digest/service.py::should_send_now() — the scheduler's
gate. No DB, no provider -- pure config + datetime logic."""
from datetime import datetime

import pytest

from ai.digest import service
from ai.digest.models import DigestType


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    monkeypatch.setattr("config.DIGEST_ENABLED", True)
    monkeypatch.setattr("config.DIGEST_WEEKLY_ENABLED", True)
    monkeypatch.setattr("config.DIGEST_MONTHLY_ENABLED", True)
    monkeypatch.setattr("config.DIGEST_WEEKLY_DAY", "MONDAY")
    monkeypatch.setattr("config.DIGEST_WEEKLY_TIME", "09:00")
    monkeypatch.setattr("config.DIGEST_MONTHLY_DAY", 1)
    monkeypatch.setattr("config.DIGEST_MONTHLY_TIME", "09:00")


def test_weekly_fires_on_the_configured_day_at_or_after_the_configured_time():
    monday_at_nine = datetime(2026, 9, 28, 9, 0)  # a Monday
    assert service.should_send_now(DigestType.WEEKLY, monday_at_nine) is True


def test_weekly_does_not_fire_before_the_configured_time():
    monday_early = datetime(2026, 9, 28, 8, 59)
    assert service.should_send_now(DigestType.WEEKLY, monday_early) is False


def test_weekly_does_not_fire_on_a_different_day():
    tuesday_at_nine = datetime(2026, 9, 29, 9, 0)
    assert service.should_send_now(DigestType.WEEKLY, tuesday_at_nine) is False


def test_weekly_short_circuits_on_master_disabled_flag(monkeypatch):
    monkeypatch.setattr("config.DIGEST_ENABLED", False)
    monday_at_nine = datetime(2026, 9, 28, 9, 0)
    assert service.should_send_now(DigestType.WEEKLY, monday_at_nine) is False


def test_weekly_short_circuits_on_its_own_sub_flag(monkeypatch):
    monkeypatch.setattr("config.DIGEST_WEEKLY_ENABLED", False)
    monday_at_nine = datetime(2026, 9, 28, 9, 0)
    assert service.should_send_now(DigestType.WEEKLY, monday_at_nine) is False


def test_monthly_fires_on_the_configured_day_at_or_after_the_configured_time():
    first_at_nine = datetime(2026, 9, 1, 9, 0)
    assert service.should_send_now(DigestType.MONTHLY, first_at_nine) is True


def test_monthly_does_not_fire_on_a_different_day():
    second_at_nine = datetime(2026, 9, 2, 9, 0)
    assert service.should_send_now(DigestType.MONTHLY, second_at_nine) is False


def test_monthly_day_clamps_into_a_shorter_month(monkeypatch):
    monkeypatch.setattr("config.DIGEST_MONTHLY_DAY", 31)
    feb_28_at_nine = datetime(2026, 2, 28, 9, 0)  # 2026 is not a leap year
    assert service.should_send_now(DigestType.MONTHLY, feb_28_at_nine) is True


def test_monthly_short_circuits_on_its_own_sub_flag(monkeypatch):
    monkeypatch.setattr("config.DIGEST_MONTHLY_ENABLED", False)
    first_at_nine = datetime(2026, 9, 1, 9, 0)
    assert service.should_send_now(DigestType.MONTHLY, first_at_nine) is False
