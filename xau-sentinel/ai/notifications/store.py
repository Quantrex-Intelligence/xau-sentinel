"""SQLite persistence for delivery state (Stage 14). One new table, added
the established way: CREATE TABLE IF NOT EXISTS through
journal.database.get_connection() (calling it, never editing it) — the
same pattern ai/monitoring/store.py already established. Neither
ai/monitoring/store.py nor its `monitoring_alerts` table is touched by
this module; delivery state for a channel is deliberately a SEPARATE
table (see ai/notifications/models.py's docstring) so "should this alert
exist" and "have I delivered it" can never be conflated.

`UNIQUE(alert_id, channel)` is the hard backstop behind
ai/notifications/delivery.py's discovery step: a second discovery of the
same alert is a silent no-op (INSERT OR IGNORE), never a duplicate row —
the same "stable identity, not a random id" dedup contract
ai/monitoring/store.py's dedup_key already uses.
"""
import sqlite3
from datetime import datetime, timezone
from typing import List, Optional, Set

from journal.database import get_connection
from ai.notifications.models import AlertDelivery, DeliveryStatus

TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS alert_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id INTEGER NOT NULL,
    channel TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TEXT,
    sent_at TEXT,
    error TEXT,
    retryable INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_alert_deliveries_alert_channel ON alert_deliveries(alert_id, channel);
"""


def init_table() -> None:
    with get_connection() as conn:
        conn.executescript(TABLE_SCHEMA)
        conn.commit()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_delivery(row: sqlite3.Row) -> AlertDelivery:
    return AlertDelivery(
        id=row["id"], alert_id=row["alert_id"], channel=row["channel"],
        status=DeliveryStatus(row["status"]), attempt_count=row["attempt_count"],
        last_attempt_at=row["last_attempt_at"], sent_at=row["sent_at"], error=row["error"],
        retryable=bool(row["retryable"]), created_at=row["created_at"],
    )


def create_pending(alert_id: int, channel: str) -> Optional[AlertDelivery]:
    """Returns the new PENDING delivery row, or None if one already exists
    for this (alert_id, channel) — a genuine duplicate, silently ignored."""
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO alert_deliveries (alert_id, channel, status, created_at) "
            "VALUES (?, ?, 'PENDING', ?)",
            (alert_id, channel, _now_iso()),
        )
        conn.commit()
        if cur.rowcount == 0:
            return None
        row = conn.execute("SELECT * FROM alert_deliveries WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _row_to_delivery(row)


def get_delivered_alert_ids(channel: str) -> Set[int]:
    """Every alert_id that already has ANY delivery row for this channel
    (PENDING, SENT, or FAILED) — i.e. already discovered, not necessarily
    already sent."""
    with get_connection() as conn:
        rows = conn.execute("SELECT alert_id FROM alert_deliveries WHERE channel = ?", (channel,)).fetchall()
    return {r["alert_id"] for r in rows}


def list_pending_and_retryable_failed(channel: str) -> List[AlertDelivery]:
    """PENDING rows are always eligible (never attempted yet); FAILED rows
    only when their last failure was retryable — a non-retryable failure
    is excluded here permanently, not just skipped for one cycle."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM alert_deliveries WHERE channel = ? AND "
            "(status = 'PENDING' OR (status = 'FAILED' AND retryable = 1)) "
            "ORDER BY id ASC",
            (channel,),
        ).fetchall()
    return [_row_to_delivery(r) for r in rows]


def mark_sent(delivery_id: int) -> AlertDelivery:
    now = _now_iso()
    with get_connection() as conn:
        conn.execute(
            "UPDATE alert_deliveries SET status = 'SENT', sent_at = ?, last_attempt_at = ?, "
            "attempt_count = attempt_count + 1, error = NULL, retryable = 1 WHERE id = ?",
            (now, now, delivery_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM alert_deliveries WHERE id = ?", (delivery_id,)).fetchone()
        return _row_to_delivery(row)


def mark_failed(delivery_id: int, error: str, retryable: bool = True) -> AlertDelivery:
    """`retryable` is persisted, not just returned transiently — a
    non-retryable failure (bad token/chat id) must stay terminal on every
    later cycle, not just skip one backoff window (see
    ai/notifications/delivery.py::attempt_deliveries())."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE alert_deliveries SET status = 'FAILED', last_attempt_at = ?, "
            "attempt_count = attempt_count + 1, error = ?, retryable = ? WHERE id = ?",
            (_now_iso(), error, 1 if retryable else 0, delivery_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM alert_deliveries WHERE id = ?", (delivery_id,)).fetchone()
        return _row_to_delivery(row)


def list_deliveries(channel: Optional[str] = None, status: Optional[str] = None,
                     limit: int = 50) -> List[AlertDelivery]:
    query = "SELECT * FROM alert_deliveries WHERE 1=1"
    params: list = []
    if channel is not None:
        query += " AND channel = ?"
        params.append(channel)
    if status is not None:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [_row_to_delivery(r) for r in rows]


def last_success_at(channel: str) -> Optional[str]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT MAX(sent_at) AS ts FROM alert_deliveries WHERE channel = ? AND status = 'SENT'",
            (channel,),
        ).fetchone()
    return row["ts"] if row else None


def last_error_at(channel: str) -> Optional[str]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT MAX(last_attempt_at) AS ts FROM alert_deliveries WHERE channel = ? AND status = 'FAILED'",
            (channel,),
        ).fetchone()
    return row["ts"] if row else None
