"""PostgreSQL persistence for delivery state (Stage 14, DEP-002). Tables are
defined in journal/schema.py alongside every other table; this module only
builds and executes Core queries against them through
journal.database.get_connection(). Delivery state for a channel is
deliberately a SEPARATE table from ai/monitoring/store.py's
`monitoring_alerts` (see ai/notifications/models.py's docstring) so "should
this alert exist" and "have I delivered it" can never be conflated.

`UNIQUE(alert_id, channel)` is the hard backstop behind
ai/notifications/delivery.py's discovery step: a second discovery of the
same alert is a silent no-op (ON CONFLICT DO NOTHING), never a duplicate row
— the same "stable identity, not a random id" dedup contract
ai/monitoring/store.py's dedup_key already uses.

DEP-011: a second, separate table, `notification_test_sends`, records the
last successful manual test send per provider (one row per provider name,
upserted). It is deliberately NOT an alert_deliveries row: a test message
is not an alert delivery, so last_success_at() keeps meaning "an alert was
really delivered" and the test result is reported on its own.
"""
from datetime import datetime, timezone
from typing import List, Optional, Set

from sqlalchemy import select, update, func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from journal.database import get_connection
from journal.schema import alert_deliveries, notification_test_sends
from ai.notifications.models import AlertDelivery, DeliveryStatus


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _row_to_delivery(row) -> AlertDelivery:
    return AlertDelivery(
        id=row.id, alert_id=row.alert_id, channel=row.channel,
        status=DeliveryStatus(row.status), attempt_count=row.attempt_count,
        last_attempt_at=row.last_attempt_at.isoformat() if row.last_attempt_at else None,
        sent_at=row.sent_at.isoformat() if row.sent_at else None, error=row.error,
        retryable=row.retryable, created_at=row.created_at.isoformat(),
    )


def create_pending(alert_id: int, channel: str) -> Optional[AlertDelivery]:
    """Returns the new PENDING delivery row, or None if one already exists
    for this (alert_id, channel) — a genuine duplicate, silently ignored."""
    with get_connection() as conn:
        stmt = pg_insert(alert_deliveries).values(
            alert_id=alert_id, channel=channel, status="PENDING", created_at=_now(),
        ).on_conflict_do_nothing(
            index_elements=["alert_id", "channel"]
        ).returning(alert_deliveries.c.id)
        result = conn.execute(stmt)
        conn.commit()
        row_id = result.scalar_one_or_none()
        if row_id is None:
            return None
        row = conn.execute(select(alert_deliveries).where(alert_deliveries.c.id == row_id)).fetchone()
        return _row_to_delivery(row)


def get_delivered_alert_ids(channel: str) -> Set[int]:
    """Every alert_id that already has ANY delivery row for this channel
    (PENDING, SENT, or FAILED) — i.e. already discovered, not necessarily
    already sent."""
    with get_connection() as conn:
        rows = conn.execute(
            select(alert_deliveries.c.alert_id).where(alert_deliveries.c.channel == channel)
        ).fetchall()
    return {r.alert_id for r in rows}


def list_pending_and_retryable_failed(channel: str) -> List[AlertDelivery]:
    """PENDING rows are always eligible (never attempted yet); FAILED rows
    only when their last failure was retryable — a non-retryable failure
    is excluded here permanently, not just skipped for one cycle."""
    with get_connection() as conn:
        rows = conn.execute(
            select(alert_deliveries)
            .where(
                alert_deliveries.c.channel == channel,
                (alert_deliveries.c.status == "PENDING")
                | ((alert_deliveries.c.status == "FAILED") & (alert_deliveries.c.retryable.is_(True))),
            )
            .order_by(alert_deliveries.c.id.asc())
        ).fetchall()
    return [_row_to_delivery(r) for r in rows]


def mark_sent(delivery_id: int) -> AlertDelivery:
    now = _now()
    with get_connection() as conn:
        conn.execute(
            update(alert_deliveries)
            .where(alert_deliveries.c.id == delivery_id)
            .values(
                status="SENT", sent_at=now, last_attempt_at=now,
                attempt_count=alert_deliveries.c.attempt_count + 1, error=None, retryable=True,
            )
        )
        conn.commit()
        row = conn.execute(select(alert_deliveries).where(alert_deliveries.c.id == delivery_id)).fetchone()
        return _row_to_delivery(row)


def mark_failed(delivery_id: int, error: str, retryable: bool = True) -> AlertDelivery:
    """`retryable` is persisted, not just returned transiently — a
    non-retryable failure (bad token/chat id) must stay terminal on every
    later cycle, not just skip one backoff window (see
    ai/notifications/delivery.py::attempt_deliveries())."""
    with get_connection() as conn:
        conn.execute(
            update(alert_deliveries)
            .where(alert_deliveries.c.id == delivery_id)
            .values(
                status="FAILED", last_attempt_at=_now(),
                attempt_count=alert_deliveries.c.attempt_count + 1, error=error, retryable=retryable,
            )
        )
        conn.commit()
        row = conn.execute(select(alert_deliveries).where(alert_deliveries.c.id == delivery_id)).fetchone()
        return _row_to_delivery(row)


def list_deliveries(channel: Optional[str] = None, status: Optional[str] = None,
                     limit: int = 50) -> List[AlertDelivery]:
    query = select(alert_deliveries)
    if channel is not None:
        query = query.where(alert_deliveries.c.channel == channel)
    if status is not None:
        query = query.where(alert_deliveries.c.status == status)
    query = query.order_by(alert_deliveries.c.id.desc()).limit(limit)
    with get_connection() as conn:
        rows = conn.execute(query).fetchall()
    return [_row_to_delivery(r) for r in rows]


def last_success_at(channel: str) -> Optional[str]:
    with get_connection() as conn:
        ts = conn.execute(
            select(func.max(alert_deliveries.c.sent_at))
            .where(alert_deliveries.c.channel == channel, alert_deliveries.c.status == "SENT")
        ).scalar()
    return ts.isoformat() if ts else None


def last_error_at(channel: str) -> Optional[str]:
    with get_connection() as conn:
        ts = conn.execute(
            select(func.max(alert_deliveries.c.last_attempt_at))
            .where(alert_deliveries.c.channel == channel, alert_deliveries.c.status == "FAILED")
        ).scalar()
    return ts.isoformat() if ts else None


def record_test_success(provider: str) -> str:
    """DEP-011: stamps a successful manual test send for `provider` (the
    provider's own name, e.g. "telegram" or "mock", so a mock-provider test
    can never read as proof the real Telegram channel works). Returns the
    stored timestamp."""
    now = _now()
    with get_connection() as conn:
        stmt = pg_insert(notification_test_sends).values(provider=provider, last_success_at=now)
        stmt = stmt.on_conflict_do_update(
            index_elements=["provider"], set_={"last_success_at": stmt.excluded.last_success_at},
        )
        conn.execute(stmt)
        conn.commit()
    return now.isoformat()


def last_test_success_at(provider: str) -> Optional[str]:
    with get_connection() as conn:
        ts = conn.execute(
            select(notification_test_sends.c.last_success_at)
            .where(notification_test_sends.c.provider == provider)
        ).scalar()
    return ts.isoformat() if ts else None
