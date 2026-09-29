"""Tests for ai/monitoring/store.py — persistence, DB-level dedup via the
UNIQUE(dedup_key) index (the hard backstop behind the engine's in-memory
diff), acknowledge/acknowledge-all, filtering, and retention purge."""
from datetime import datetime, timedelta, timezone

import pytest

from ai.monitoring import store
from ai.monitoring.models import AlertEvent, AlertType, Severity


@pytest.fixture(autouse=True)
def _init(temp_db):
    store.init_table()


def _alert(**overrides):
    defaults = dict(
        type=AlertType.SETUP_STATE_CHANGED, severity=Severity.INFO, title="t", message="m",
        dedup_key="key-1", payload={"a": 1},
    )
    defaults.update(overrides)
    return AlertEvent(**defaults)


def test_create_alert_persists_and_returns_assigned_id():
    created = store.create_alert(_alert())
    assert created is not None
    assert created.id is not None


def test_create_alert_with_duplicate_dedup_key_returns_none():
    first = store.create_alert(_alert(dedup_key="same-key"))
    second = store.create_alert(_alert(dedup_key="same-key", title="different title"))
    assert first is not None
    assert second is None
    assert len(store.list_alerts(limit=100)) == 1


def test_create_alert_with_different_dedup_key_creates_a_new_row():
    store.create_alert(_alert(dedup_key="key-a"))
    store.create_alert(_alert(dedup_key="key-b"))
    assert len(store.list_alerts(limit=100)) == 2


def test_list_alerts_filters_by_type():
    store.create_alert(_alert(dedup_key="k1", type=AlertType.SETUP_STATE_CHANGED))
    store.create_alert(_alert(dedup_key="k2", type=AlertType.RISK_STATUS_CHANGED))
    filtered = store.list_alerts(alert_type="RISK_STATUS_CHANGED")
    assert len(filtered) == 1
    assert filtered[0].type == AlertType.RISK_STATUS_CHANGED


def test_list_alerts_filters_by_severity():
    store.create_alert(_alert(dedup_key="k1", severity=Severity.INFO))
    store.create_alert(_alert(dedup_key="k2", severity=Severity.CRITICAL))
    filtered = store.list_alerts(severity="CRITICAL")
    assert len(filtered) == 1
    assert filtered[0].severity == Severity.CRITICAL


def test_list_alerts_filters_by_acknowledged():
    a = store.create_alert(_alert(dedup_key="k1"))
    store.create_alert(_alert(dedup_key="k2"))
    store.acknowledge(a.id)

    unread = store.list_alerts(acknowledged=False)
    read = store.list_alerts(acknowledged=True)
    assert len(unread) == 1
    assert len(read) == 1
    assert read[0].id == a.id


def test_list_alerts_respects_limit_and_newest_first():
    for i in range(5):
        store.create_alert(_alert(dedup_key=f"k{i}", title=f"alert {i}"))
    limited = store.list_alerts(limit=2)
    assert len(limited) == 2
    assert limited[0].title == "alert 4"


def test_acknowledge_sets_flag_and_returns_true():
    a = store.create_alert(_alert(dedup_key="k1"))
    assert a.acknowledged is False
    ok = store.acknowledge(a.id)
    assert ok is True
    reloaded = store.list_alerts(limit=100)[0]
    assert reloaded.acknowledged is True


def test_acknowledge_unknown_id_returns_false():
    assert store.acknowledge(99999) is False


def test_acknowledge_all_marks_every_unread_alert():
    store.create_alert(_alert(dedup_key="k1"))
    store.create_alert(_alert(dedup_key="k2"))
    count = store.acknowledge_all()
    assert count == 2
    assert store.list_alerts(acknowledged=False) == []


def test_acknowledge_all_is_idempotent_and_never_errors_on_empty_table():
    assert store.acknowledge_all() == 0


def test_acknowledge_only_touches_the_acknowledged_column():
    a = store.create_alert(_alert(dedup_key="k1", payload={"entry": 3700.0}))
    store.acknowledge(a.id)
    reloaded = store.list_alerts(limit=100)[0]
    assert reloaded.payload == {"entry": 3700.0}
    assert reloaded.title == a.title
    assert reloaded.dedup_key == a.dedup_key


def test_purge_older_than_removes_old_rows_only():
    with_old_and_new = store.create_alert(_alert(dedup_key="new"))
    from journal.database import get_connection
    old_time = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO monitoring_alerts (alert_type, severity, title, message, symbol, payload,
               dedup_key, acknowledged, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)""",
            ("SETUP_STATE_CHANGED", "INFO", "old", "old alert", "XAUUSD", "{}", "old-key", old_time),
        )
        conn.commit()

    removed = store.purge_older_than(30)
    assert removed == 1
    remaining = store.list_alerts(limit=100)
    assert len(remaining) == 1
    assert remaining[0].id == with_old_and_new.id
