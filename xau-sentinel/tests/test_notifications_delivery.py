"""Tests for ai/notifications/delivery.py — the worker that discovers new
monitoring alerts and delivers them, entirely through ai.monitoring.store's
existing, unmodified list_alerts(). Covers discovery -> PENDING, success ->
SENT, failure -> FAILED, backoff/retry-limit behavior, the UNIQUE(alert_id,
channel) dedup guarantee, that a Telegram outage never deletes the
underlying monitoring alert, and structural guarantees that this module
never re-runs the deterministic engine or calls an LLM.
"""
import inspect
import time

import pytest

from ai.monitoring.models import AlertEvent, AlertType, Severity
from ai.monitoring import store as monitoring_store
from ai.notifications import delivery, store
from ai.notifications.models import DeliveryResult, DeliveryStatus


@pytest.fixture(autouse=True)
def _init_tables(temp_db):
    monitoring_store.init_table()
    store.init_table()


def _seed_monitoring_alert(dedup_key="k1", **overrides):
    defaults = dict(
        type=AlertType.SETUP_STATE_CHANGED, severity=Severity.INFO, title="Setup changed",
        message="NO SETUP -> DEVELOPING", dedup_key=dedup_key, payload={},
    )
    defaults.update(overrides)
    return monitoring_store.create_alert(AlertEvent(**defaults))


class _RecordingProvider:
    def __init__(self, results=None):
        self._results = list(results) if results is not None else None
        self.sent_messages = []

    def send(self, message):
        self.sent_messages.append(message)
        if self._results is not None:
            return self._results.pop(0)
        return DeliveryResult(success=True)


@pytest.fixture
def _mock_provider(monkeypatch):
    provider = _RecordingProvider()
    monkeypatch.setattr(delivery, "get_notification_provider", lambda: provider)
    return provider


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def test_discover_new_alerts_creates_a_pending_delivery():
    alert = _seed_monitoring_alert()
    created = delivery.discover_new_alerts()
    assert created == 1
    pending = store.list_pending_and_retryable_failed("telegram")
    assert len(pending) == 1
    assert pending[0].alert_id == alert.id


def test_discover_new_alerts_does_not_create_duplicates_across_calls():
    _seed_monitoring_alert()
    delivery.discover_new_alerts()
    second_pass = delivery.discover_new_alerts()
    assert second_pass == 0
    assert len(store.list_deliveries(limit=100)) == 1


def test_discover_new_alerts_handles_multiple_alerts():
    _seed_monitoring_alert(dedup_key="k1")
    _seed_monitoring_alert(dedup_key="k2")
    created = delivery.discover_new_alerts()
    assert created == 2


# ---------------------------------------------------------------------------
# Delivery attempts
# ---------------------------------------------------------------------------

def test_successful_delivery_becomes_sent(_mock_provider):
    _seed_monitoring_alert()
    delivery.discover_new_alerts()
    attempted = delivery.attempt_deliveries()

    assert len(attempted) == 1
    assert attempted[0].status == DeliveryStatus.SENT
    assert len(_mock_provider.sent_messages) == 1


def test_failed_delivery_becomes_failed(monkeypatch):
    provider = _RecordingProvider(results=[DeliveryResult(success=False, error="boom", retryable=True)])
    monkeypatch.setattr(delivery, "get_notification_provider", lambda: provider)
    _seed_monitoring_alert()
    delivery.discover_new_alerts()
    attempted = delivery.attempt_deliveries()

    assert attempted[0].status == DeliveryStatus.FAILED
    assert attempted[0].error == "boom"


def test_already_sent_alert_is_never_resent(_mock_provider):
    _seed_monitoring_alert()
    delivery.discover_new_alerts()
    delivery.attempt_deliveries()
    again = delivery.attempt_deliveries()

    assert again == []
    assert len(_mock_provider.sent_messages) == 1


def test_run_delivery_cycle_discovers_and_attempts_in_one_call(_mock_provider):
    _seed_monitoring_alert()
    attempted = delivery.run_delivery_cycle()
    assert len(attempted) == 1
    assert attempted[0].status == DeliveryStatus.SENT


# ---------------------------------------------------------------------------
# Retry / backoff / max retries
# ---------------------------------------------------------------------------

def test_retryable_failure_is_retried_after_backoff_window(monkeypatch):
    monkeypatch.setattr("config.TELEGRAM_RETRY_BACKOFF_SECONDS", 0.01)
    monkeypatch.setattr("config.TELEGRAM_MAX_RETRIES", 5)
    provider = _RecordingProvider(results=[
        DeliveryResult(success=False, error="boom", retryable=True),
        DeliveryResult(success=True),
    ])
    monkeypatch.setattr(delivery, "get_notification_provider", lambda: provider)

    _seed_monitoring_alert()
    delivery.discover_new_alerts()
    first = delivery.attempt_deliveries()
    assert first[0].status == DeliveryStatus.FAILED

    time.sleep(0.05)
    second = delivery.attempt_deliveries()
    assert second[0].status == DeliveryStatus.SENT


def test_failure_within_backoff_window_is_not_retried_yet(monkeypatch):
    monkeypatch.setattr("config.TELEGRAM_RETRY_BACKOFF_SECONDS", 60)
    provider = _RecordingProvider(results=[DeliveryResult(success=False, error="boom", retryable=True)])
    monkeypatch.setattr(delivery, "get_notification_provider", lambda: provider)

    _seed_monitoring_alert()
    delivery.discover_new_alerts()
    delivery.attempt_deliveries()
    immediately_again = delivery.attempt_deliveries()
    assert immediately_again == []


def test_max_retries_exhausted_stops_further_attempts(monkeypatch):
    monkeypatch.setattr("config.TELEGRAM_RETRY_BACKOFF_SECONDS", 0.01)
    monkeypatch.setattr("config.TELEGRAM_MAX_RETRIES", 2)
    provider = _RecordingProvider(results=[
        DeliveryResult(success=False, error="boom", retryable=True),
        DeliveryResult(success=False, error="boom", retryable=True),
        DeliveryResult(success=True),
    ])
    monkeypatch.setattr(delivery, "get_notification_provider", lambda: provider)

    _seed_monitoring_alert()
    delivery.discover_new_alerts()
    delivery.attempt_deliveries()
    time.sleep(0.05)
    delivery.attempt_deliveries()  # attempt_count now == TELEGRAM_MAX_RETRIES (2)
    time.sleep(0.05)
    third = delivery.attempt_deliveries()

    assert third == []
    assert len(provider.sent_messages) == 2  # never reached the 3rd, successful result


def test_non_retryable_failure_is_never_retried(monkeypatch):
    monkeypatch.setattr("config.TELEGRAM_RETRY_BACKOFF_SECONDS", 0.01)
    provider = _RecordingProvider(results=[DeliveryResult(success=False, error="bad token", retryable=False)])
    monkeypatch.setattr(delivery, "get_notification_provider", lambda: provider)

    _seed_monitoring_alert()
    delivery.discover_new_alerts()
    delivery.attempt_deliveries()
    time.sleep(0.05)
    again = delivery.attempt_deliveries()
    assert again == []
    assert len(provider.sent_messages) == 1


# ---------------------------------------------------------------------------
# Recovery: Telegram outage never deletes the monitoring alert
# ---------------------------------------------------------------------------

def test_delivery_failure_never_deletes_the_monitoring_alert(monkeypatch):
    provider = _RecordingProvider(results=[DeliveryResult(success=False, error="boom", retryable=True)])
    monkeypatch.setattr(delivery, "get_notification_provider", lambda: provider)

    alert = _seed_monitoring_alert()
    delivery.discover_new_alerts()
    delivery.attempt_deliveries()

    still_there = [a for a in monitoring_store.list_alerts(limit=100) if a.id == alert.id]
    assert len(still_there) == 1


def test_recovery_delivers_the_same_alert_without_regenerating_it(monkeypatch):
    monkeypatch.setattr("config.TELEGRAM_RETRY_BACKOFF_SECONDS", 0.01)
    provider = _RecordingProvider(results=[
        DeliveryResult(success=False, error="Telegram unavailable", retryable=True),
        DeliveryResult(success=True),
    ])
    monkeypatch.setattr(delivery, "get_notification_provider", lambda: provider)

    alert = _seed_monitoring_alert()
    delivery.run_delivery_cycle()  # discover + fail
    time.sleep(0.05)
    delivery.run_delivery_cycle()  # discover (no-op, already tracked) + succeed

    deliveries = store.list_deliveries(limit=100)
    assert len(deliveries) == 1  # never a second delivery row for the same alert
    assert deliveries[0].alert_id == alert.id
    assert deliveries[0].status == DeliveryStatus.SENT


# ---------------------------------------------------------------------------
# Missing/config errors degrade gracefully
# ---------------------------------------------------------------------------

def test_config_error_skips_the_cycle_without_marking_deliveries_failed(monkeypatch):
    from ai.notifications.providers.telegram import NotificationConfigError

    def raise_config_error():
        raise NotificationConfigError("not configured")
    monkeypatch.setattr(delivery, "get_notification_provider", raise_config_error)

    _seed_monitoring_alert()
    delivery.discover_new_alerts()
    attempted = delivery.attempt_deliveries()

    assert attempted == []
    pending = store.list_pending_and_retryable_failed("telegram")
    assert pending[0].status == DeliveryStatus.PENDING  # untouched, not marked FAILED


def test_purged_underlying_alert_is_skipped_not_crashed(_mock_provider):
    """If ALERT_RETENTION_DAYS purged the monitoring_alerts row between
    discovery and attempt, the delivery worker must degrade, not crash."""
    from journal.database import get_connection

    _seed_monitoring_alert()
    delivery.discover_new_alerts()
    with get_connection() as conn:
        conn.execute("DELETE FROM monitoring_alerts")
        conn.commit()

    attempted = delivery.attempt_deliveries()
    assert attempted == []


# ---------------------------------------------------------------------------
# Structural guarantees
# ---------------------------------------------------------------------------

def test_delivery_module_never_calls_the_deterministic_evaluator_or_an_llm():
    source = inspect.getsource(delivery)
    for banned in (
        "evaluate_deterministic", "evaluate_current_setup", "get_provider", ".chat(",
        "attach_llm_explanation", "detect_setup", "compute_status", "build_market_intelligence_context",
    ):
        assert banned not in source


def test_delivery_module_never_writes_to_trades_or_journal():
    source = inspect.getsource(delivery)
    for banned in ("trades_repo", "journal.trades", "INSERT INTO trades", "conn.execute"):
        assert banned not in source


def test_monitoring_engine_never_imports_notifications():
    """The inverse structural guarantee: ai/monitoring/ must never import
    anything Telegram-specific."""
    from ai.monitoring import engine as monitoring_engine, rules as monitoring_rules
    for module in (monitoring_engine, monitoring_rules):
        source = inspect.getsource(module)
        assert "telegram" not in source.lower()
        assert "notifications" not in source.lower()
