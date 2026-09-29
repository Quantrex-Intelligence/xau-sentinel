"""Digest delivery dedup store (Stage 18) — mirrors
ai/monitoring/store.py's INSERT OR IGNORE + UNIQUE-index + rowcount idiom.
Only successful sends are ever recorded here; a failed send records
nothing, so the next scheduled poll cycle retries naturally (see
ai/digest/service.py::run_digest_cycle()) — no separate status/retry-count
column is needed for something that fires at most twice a week per type.
"""
from datetime import date, datetime, timezone
from typing import Optional

from journal.database import get_connection

TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS digest_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    digest_type TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    channel TEXT NOT NULL,
    sent_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_digest_deliveries_identity
    ON digest_deliveries(digest_type, period_start, period_end, channel);
"""


def init_table() -> None:
    with get_connection() as conn:
        conn.executescript(TABLE_SCHEMA)
        conn.commit()


def was_sent(digest_type: str, period_start: date, period_end: date, channel: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            """SELECT 1 FROM digest_deliveries
               WHERE digest_type = ? AND period_start = ? AND period_end = ? AND channel = ?""",
            (digest_type, period_start.isoformat(), period_end.isoformat(), channel),
        ).fetchone()
        return row is not None


def record_sent(digest_type: str, period_start: date, period_end: date, channel: str) -> bool:
    """Returns True if this call newly recorded the send, False if a row
    for this exact identity already existed (a genuine duplicate, silently
    ignored rather than raising — same convention as
    ai/monitoring/store.py::create_alert())."""
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT OR IGNORE INTO digest_deliveries (digest_type, period_start, period_end, channel, sent_at)
               VALUES (?, ?, ?, ?, ?)""",
            (digest_type, period_start.isoformat(), period_end.isoformat(), channel,
             datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return cur.rowcount > 0


def last_sent(digest_type: str, channel: str = "telegram") -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            """SELECT period_start, period_end, sent_at FROM digest_deliveries
               WHERE digest_type = ? AND channel = ? ORDER BY id DESC LIMIT 1""",
            (digest_type, channel),
        ).fetchone()
        return dict(row) if row else None
