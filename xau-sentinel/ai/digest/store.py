"""Digest delivery dedup store (Stage 18, DEP-002) — mirrors
ai/monitoring/store.py's ON CONFLICT DO NOTHING + UNIQUE-constraint +
rowcount idiom. Only successful sends are ever recorded here; a failed send
records nothing, so the next scheduled poll cycle retries naturally (see
ai/digest/service.py::run_digest_cycle()) — no separate status/retry-count
column is needed for something that fires at most twice a week per type.
Table is defined in journal/schema.py alongside every other table; this
module only builds and executes Core queries against it through
journal.database.get_connection().
"""
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from journal.database import get_connection
from journal.schema import digest_deliveries


def was_sent(digest_type: str, period_start: date, period_end: date, channel: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            select(digest_deliveries.c.id).where(
                digest_deliveries.c.digest_type == digest_type,
                digest_deliveries.c.period_start == period_start,
                digest_deliveries.c.period_end == period_end,
                digest_deliveries.c.channel == channel,
            )
        ).fetchone()
        return row is not None


def record_sent(digest_type: str, period_start: date, period_end: date, channel: str) -> bool:
    """Returns True if this call newly recorded the send, False if a row
    for this exact identity already existed (a genuine duplicate, silently
    ignored rather than raising — same convention as
    ai/monitoring/store.py::create_alert())."""
    with get_connection() as conn:
        stmt = pg_insert(digest_deliveries).values(
            digest_type=digest_type, period_start=period_start, period_end=period_end,
            channel=channel, sent_at=datetime.now(timezone.utc),
        ).on_conflict_do_nothing(
            index_elements=["digest_type", "period_start", "period_end", "channel"]
        ).returning(digest_deliveries.c.id)
        result = conn.execute(stmt)
        conn.commit()
        return result.scalar_one_or_none() is not None


def last_sent(digest_type: str, channel: str = "telegram") -> Optional[dict]:
    """Returns period_start/period_end/sent_at as ISO 8601 strings — the
    pre-DEP-002 shape callers (e.g. api/routes/digest.py's Optional[str]
    schema fields) already expect, even though the columns are now real
    Date/TIMESTAMPTZ types."""
    with get_connection() as conn:
        row = conn.execute(
            select(digest_deliveries.c.period_start, digest_deliveries.c.period_end, digest_deliveries.c.sent_at)
            .where(digest_deliveries.c.digest_type == digest_type, digest_deliveries.c.channel == channel)
            .order_by(digest_deliveries.c.id.desc())
            .limit(1)
        ).fetchone()
        if row is None:
            return None
        return {
            "period_start": row.period_start.isoformat(),
            "period_end": row.period_end.isoformat(),
            "sent_at": row.sent_at.isoformat(),
        }
