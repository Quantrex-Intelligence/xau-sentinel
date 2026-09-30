"""Tests for ai/notifications/store.py — persistence, the UNIQUE(alert_id,
channel) dedup backstop, and status-derivation queries."""
import pytest

from ai.notifications import store
from ai.notifications.models import DeliveryStatus


@pytest.fixture(autouse=True)
def _init(temp_db):
    return temp_db


def test_create_pending_persists_a_new_row():
    delivery = store.create_pending(1, "telegram")
    assert delivery is not None
    assert delivery.status == DeliveryStatus.PENDING
    assert delivery.attempt_count == 0


def test_create_pending_with_duplicate_alert_and_channel_returns_none():
    first = store.create_pending(1, "telegram")
    second = store.create_pending(1, "telegram")
    assert first is not None
    assert second is None
    assert len(store.list_deliveries(limit=100)) == 1


def test_create_pending_same_alert_different_channel_is_allowed():
    store.create_pending(1, "telegram")
    other = store.create_pending(1, "other-channel")
    assert other is not None
    assert len(store.list_deliveries(limit=100)) == 2


def test_get_delivered_alert_ids_includes_pending_and_sent_and_failed():
    a = store.create_pending(1, "telegram")
    b = store.create_pending(2, "telegram")
    store.mark_sent(a.id)
    store.mark_failed(b.id, "boom")
    ids = store.get_delivered_alert_ids("telegram")
    assert ids == {1, 2}


def test_list_pending_and_retryable_failed_excludes_sent():
    a = store.create_pending(1, "telegram")
    store.create_pending(2, "telegram")
    store.mark_sent(a.id)
    pending = store.list_pending_and_retryable_failed("telegram")
    assert len(pending) == 1
    assert pending[0].alert_id == 2


def test_mark_sent_sets_status_and_sent_at_and_increments_attempts():
    d = store.create_pending(1, "telegram")
    updated = store.mark_sent(d.id)
    assert updated.status == DeliveryStatus.SENT
    assert updated.sent_at is not None
    assert updated.attempt_count == 1
    assert updated.error is None


def test_mark_failed_sets_status_and_error_and_increments_attempts():
    d = store.create_pending(1, "telegram")
    updated = store.mark_failed(d.id, "simulated failure")
    assert updated.status == DeliveryStatus.FAILED
    assert updated.error == "simulated failure"
    assert updated.attempt_count == 1
    assert updated.sent_at is None


def test_mark_sent_clears_a_previous_error():
    d = store.create_pending(1, "telegram")
    store.mark_failed(d.id, "first failure")
    updated = store.mark_sent(d.id)
    assert updated.status == DeliveryStatus.SENT
    assert updated.error is None


def test_list_deliveries_filters_by_channel_and_status():
    a = store.create_pending(1, "telegram")
    store.create_pending(2, "telegram")
    store.mark_sent(a.id)
    sent_only = store.list_deliveries(channel="telegram", status="SENT")
    assert len(sent_only) == 1
    assert sent_only[0].alert_id == 1


def test_last_success_at_reflects_most_recent_sent_delivery():
    assert store.last_success_at("telegram") is None
    d = store.create_pending(1, "telegram")
    store.mark_sent(d.id)
    assert store.last_success_at("telegram") is not None


def test_last_error_at_reflects_most_recent_failed_delivery():
    assert store.last_error_at("telegram") is None
    d = store.create_pending(1, "telegram")
    store.mark_failed(d.id, "boom")
    assert store.last_error_at("telegram") is not None


def test_last_success_and_error_are_scoped_per_channel():
    a = store.create_pending(1, "telegram")
    store.mark_sent(a.id)
    assert store.last_success_at("other-channel") is None


def test_mark_failed_persists_retryable_flag():
    d = store.create_pending(1, "telegram")
    updated = store.mark_failed(d.id, "bad token", retryable=False)
    assert updated.retryable is False


def test_list_pending_and_retryable_failed_excludes_non_retryable_failures():
    a = store.create_pending(1, "telegram")
    store.create_pending(2, "telegram")
    store.mark_failed(a.id, "bad token", retryable=False)
    eligible = store.list_pending_and_retryable_failed("telegram")
    assert len(eligible) == 1
    assert eligible[0].alert_id == 2


def test_mark_sent_resets_retryable_to_true():
    d = store.create_pending(1, "telegram")
    store.mark_failed(d.id, "boom", retryable=False)
    updated = store.mark_sent(d.id)
    assert updated.retryable is True
