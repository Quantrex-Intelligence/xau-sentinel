"""Regression test for BUG-2 (see final report): market events were only
deduped in Streamlit's per-session state, so every new browser session
re-logged identical historical events into the database."""
from datetime import datetime, timezone

from journal import trades as trades_repo


def test_logging_the_same_event_twice_does_not_duplicate(temp_db):
    ts = datetime(2026, 1, 5, 10, 30, tzinfo=timezone.utc)
    trades_repo.log_event("liquidity", "Previous Day High swept", "M5", ts)
    trades_repo.log_event("liquidity", "Previous Day High swept", "M5", ts)  # simulates a fresh session re-logging it
    trades_repo.log_event("liquidity", "Previous Day High swept", "M5", ts)

    events = trades_repo.recent_events(limit=10)
    assert len(events) == 1


def test_genuinely_different_events_are_not_deduped(temp_db):
    ts1 = datetime(2026, 1, 5, 10, 30, tzinfo=timezone.utc)
    ts2 = datetime(2026, 1, 5, 10, 35, tzinfo=timezone.utc)
    trades_repo.log_event("liquidity", "Previous Day High swept", "M5", ts1)
    trades_repo.log_event("liquidity", "Previous Day High swept", "M5", ts2)  # different time -> genuinely new
    trades_repo.log_event("liquidity", "Asian High swept", "M5", ts1)  # different description -> genuinely new

    events = trades_repo.recent_events(limit=10)
    assert len(events) == 3
