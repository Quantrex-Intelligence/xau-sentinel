"""PostgreSQL persistence for monitoring alerts (DEP-002). Tables are
defined in journal/schema.py alongside every other table; this module only
builds and executes Core queries against them through
journal.database.get_connection().

`dedup_key` is UNIQUE at the database level — this is the hard backstop
behind ai/monitoring/engine.py's in-memory snapshot diff: even a race or a
server restart mid-cycle can never insert two rows for the same underlying
transition. A repeat insert is silently a no-op (ON CONFLICT DO NOTHING),
never an error. (Stage 23B, VAL-019: this holds for all six alert types only
because ai/monitoring/rules.py keys transitions on the baseline snapshot's
timestamp, not the cycle's own — a cycle-timestamped key would be unique
per retry and slip straight past this constraint.)

DEP-004: a second table, `monitoring_baseline`, holds exactly one row
(`id` is pinned to 1 by a CHECK constraint) — the engine's last
MonitoringSnapshot as JSON plus the UTC time it was saved — so the first
cycle after a restart can diff against the pre-restart state instead of
silently re-baselining. It only ever stores the compact comparison
snapshot, never candles or evaluation objects.
"""
import dataclasses
import json
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from sqlalchemy import select, insert, update, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

from journal.database import get_connection
from journal.schema import monitoring_alerts, monitoring_baseline
from ai.monitoring.models import AlertEvent, AlertType, MonitoringSnapshot, Severity


def _row_to_alert(row) -> AlertEvent:
    try:
        payload = json.loads(row.payload or "{}")
    except (TypeError, ValueError):
        payload = {}
    return AlertEvent(
        id=row.id, type=AlertType(row.alert_type), severity=Severity(row.severity),
        title=row.title, message=row.message, symbol=row.symbol,
        payload=payload, dedup_key=row.dedup_key, acknowledged=row.acknowledged,
        timestamp=row.created_at.isoformat(),
    )


def create_alert(alert: AlertEvent) -> Optional[AlertEvent]:
    """Returns the persisted alert (with its assigned id), or None if an
    alert with this exact dedup_key already exists (a genuine duplicate,
    silently ignored rather than raising). `created_at` is written
    explicitly as an aware UTC datetime (this project's established
    convention, e.g. ai/memory/store.py) rather than relying on a
    server-side default."""
    with get_connection() as conn:
        stmt = pg_insert(monitoring_alerts).values(
            alert_type=alert.type.value, severity=alert.severity.value, title=alert.title,
            message=alert.message, symbol=alert.symbol, payload=json.dumps(alert.payload),
            dedup_key=alert.dedup_key, acknowledged=False, created_at=datetime.now(timezone.utc),
        ).on_conflict_do_nothing(index_elements=["dedup_key"]).returning(monitoring_alerts.c.id)
        result = conn.execute(stmt)
        conn.commit()
        row_id = result.scalar_one_or_none()
        if row_id is None:
            return None
        row = conn.execute(select(monitoring_alerts).where(monitoring_alerts.c.id == row_id)).fetchone()
        return _row_to_alert(row)


def get_by_id(alert_id: int) -> Optional[AlertEvent]:
    """A plain indexed single-row lookup — added for Stage 15's explanation
    layer, which needs to fetch one specific alert by id rather than
    scanning list_alerts(). Read-only; no detection/rule logic here."""
    with get_connection() as conn:
        row = conn.execute(select(monitoring_alerts).where(monitoring_alerts.c.id == alert_id)).fetchone()
    return _row_to_alert(row) if row else None


def list_alerts(alert_type: Optional[str] = None, severity: Optional[str] = None,
                 acknowledged: Optional[bool] = None, limit: int = 50) -> List[AlertEvent]:
    query = select(monitoring_alerts)
    if alert_type is not None:
        query = query.where(monitoring_alerts.c.alert_type == alert_type)
    if severity is not None:
        query = query.where(monitoring_alerts.c.severity == severity)
    if acknowledged is not None:
        query = query.where(monitoring_alerts.c.acknowledged == acknowledged)
    query = query.order_by(monitoring_alerts.c.id.desc()).limit(limit)

    with get_connection() as conn:
        rows = conn.execute(query).fetchall()
    return [_row_to_alert(r) for r in rows]


def acknowledge(alert_id: int) -> bool:
    """Only ever sets `acknowledged`. Never touches trades, strategy state,
    market data, risk calculations, or A+ ratings — this table has no
    columns for any of those."""
    with get_connection() as conn:
        result = conn.execute(
            update(monitoring_alerts).where(monitoring_alerts.c.id == alert_id).values(acknowledged=True)
        )
        conn.commit()
        return result.rowcount > 0


def acknowledge_all() -> int:
    with get_connection() as conn:
        result = conn.execute(
            update(monitoring_alerts).where(monitoring_alerts.c.acknowledged.is_(False)).values(acknowledged=True)
        )
        conn.commit()
        return result.rowcount


def purge_older_than(days: float) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    with get_connection() as conn:
        result = conn.execute(delete(monitoring_alerts).where(monitoring_alerts.c.created_at < cutoff))
        conn.commit()
        return result.rowcount


# ---------------------------------------------------------------------------
# DEP-004: persisted monitoring baseline (one row)
# ---------------------------------------------------------------------------

def save_baseline(snapshot: MonitoringSnapshot, saved_at: Optional[datetime] = None) -> None:
    """Upserts the single baseline row. Every MonitoringSnapshot field is
    serialized, optional ones included (aplus_candidate_key,
    nearby_high_impact_event_key), so a restored baseline diffs exactly like
    the in-memory one did."""
    saved = saved_at or datetime.now(timezone.utc)
    with get_connection() as conn:
        stmt = pg_insert(monitoring_baseline).values(
            id=1, snapshot=json.dumps(dataclasses.asdict(snapshot)), saved_at=saved,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"], set_={"snapshot": stmt.excluded.snapshot, "saved_at": stmt.excluded.saved_at},
        )
        conn.execute(stmt)
        conn.commit()


def load_baseline() -> Optional[Tuple[MonitoringSnapshot, datetime]]:
    """Returns (snapshot, saved_at), or None when there is no row, or the
    row can't be rebuilt into a MonitoringSnapshot (corrupt JSON, a missing
    required field, an unparseable saved_at). An unreadable baseline is
    treated like no baseline at all: never guessed at. Unknown keys (from a
    future schema) are ignored; missing optional fields take their
    defaults."""
    with get_connection() as conn:
        row = conn.execute(
            select(monitoring_baseline.c.snapshot, monitoring_baseline.c.saved_at)
            .where(monitoring_baseline.c.id == 1)
        ).fetchone()
    if row is None:
        return None
    try:
        data = json.loads(row.snapshot)
        known = {f.name for f in dataclasses.fields(MonitoringSnapshot)}
        snapshot = MonitoringSnapshot(**{k: v for k, v in data.items() if k in known})
        saved_at = row.saved_at
    except (TypeError, ValueError, AttributeError):
        return None
    if saved_at.tzinfo is None:
        saved_at = saved_at.replace(tzinfo=timezone.utc)
    return snapshot, saved_at


def clear_baseline() -> None:
    with get_connection() as conn:
        conn.execute(delete(monitoring_baseline))
        conn.commit()
