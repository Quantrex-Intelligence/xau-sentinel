"""SQLite persistence for monitoring alerts. One new table, added the
established way: CREATE TABLE IF NOT EXISTS through
journal.database.get_connection() (calling it, never editing it) — the
same pattern as ai/memory/store.py, ai/knowledge/store.py, and
risk/fundednext_journal.py. The frozen Stage 1 schema in
journal/database.py (including its OWN, unrelated `alerts` table) is never
touched.

`dedup_key` is UNIQUE at the database level — this is the hard backstop
behind ai/monitoring/engine.py's in-memory snapshot diff: even a race or a
server restart mid-cycle can never insert two rows for the same underlying
transition. A repeat insert is silently a no-op (INSERT OR IGNORE), never
an error. (Stage 23B, VAL-019: this holds for all six alert types only
because ai/monitoring/rules.py keys transitions on the baseline snapshot's
timestamp, not the cycle's own — a cycle-timestamped key would be unique
per retry and slip straight past this index.)

DEP-004: a second new table, `monitoring_baseline`, holds exactly one row
(`id` is pinned to 1 by a CHECK constraint) — the engine's last
MonitoringSnapshot as JSON plus the UTC time it was saved — so the first
cycle after a restart can diff against the pre-restart state instead of
silently re-baselining. It only ever stores the compact comparison
snapshot, never candles or evaluation objects.
"""
import dataclasses
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from journal.database import get_connection
from ai.monitoring.models import AlertEvent, AlertType, MonitoringSnapshot, Severity

TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS monitoring_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    symbol TEXT NOT NULL DEFAULT 'XAUUSD',
    payload TEXT NOT NULL,
    dedup_key TEXT NOT NULL,
    acknowledged INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_monitoring_alerts_dedup_key ON monitoring_alerts(dedup_key);
CREATE TABLE IF NOT EXISTS monitoring_baseline (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    snapshot TEXT NOT NULL,
    saved_at TEXT NOT NULL
);
"""


def init_table() -> None:
    with get_connection() as conn:
        conn.executescript(TABLE_SCHEMA)
        conn.commit()


def _row_to_alert(row: sqlite3.Row) -> AlertEvent:
    try:
        payload = json.loads(row["payload"] or "{}")
    except (TypeError, ValueError):
        payload = {}
    return AlertEvent(
        id=row["id"], type=AlertType(row["alert_type"]), severity=Severity(row["severity"]),
        title=row["title"], message=row["message"], symbol=row["symbol"],
        payload=payload, dedup_key=row["dedup_key"], acknowledged=bool(row["acknowledged"]),
        timestamp=row["created_at"],
    )


def create_alert(alert: AlertEvent) -> Optional[AlertEvent]:
    """Returns the persisted alert (with its assigned id), or None if an
    alert with this exact dedup_key already exists (a genuine duplicate,
    silently ignored rather than raising). `created_at` is written
    explicitly as an ISO 8601 UTC string (this project's established
    convention, e.g. ai/memory/store.py) rather than relying on the
    schema's bare `datetime('now')` default, which is naive and
    space-separated."""
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT OR IGNORE INTO monitoring_alerts
               (alert_type, severity, title, message, symbol, payload, dedup_key, acknowledged, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)""",
            (alert.type.value, alert.severity.value, alert.title, alert.message, alert.symbol,
             json.dumps(alert.payload), alert.dedup_key, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        if cur.rowcount == 0:
            return None
        row = conn.execute("SELECT * FROM monitoring_alerts WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _row_to_alert(row)


def get_by_id(alert_id: int) -> Optional[AlertEvent]:
    """A plain indexed single-row lookup — added for Stage 15's explanation
    layer, which needs to fetch one specific alert by id rather than
    scanning list_alerts(). Read-only; no detection/rule logic here."""
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM monitoring_alerts WHERE id = ?", (alert_id,)).fetchone()
    return _row_to_alert(row) if row else None


def list_alerts(alert_type: Optional[str] = None, severity: Optional[str] = None,
                 acknowledged: Optional[bool] = None, limit: int = 50) -> List[AlertEvent]:
    query = "SELECT * FROM monitoring_alerts WHERE 1=1"
    params: list = []
    if alert_type is not None:
        query += " AND alert_type = ?"
        params.append(alert_type)
    if severity is not None:
        query += " AND severity = ?"
        params.append(severity)
    if acknowledged is not None:
        query += " AND acknowledged = ?"
        params.append(1 if acknowledged else 0)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [_row_to_alert(r) for r in rows]


def acknowledge(alert_id: int) -> bool:
    """Only ever sets `acknowledged`. Never touches trades, strategy state,
    market data, risk calculations, or A+ ratings — this table has no
    columns for any of those."""
    with get_connection() as conn:
        cur = conn.execute("UPDATE monitoring_alerts SET acknowledged = 1 WHERE id = ?", (alert_id,))
        conn.commit()
        return cur.rowcount > 0


def acknowledge_all() -> int:
    with get_connection() as conn:
        cur = conn.execute("UPDATE monitoring_alerts SET acknowledged = 1 WHERE acknowledged = 0")
        conn.commit()
        return cur.rowcount


def purge_older_than(days: float) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM monitoring_alerts WHERE created_at < ?", (cutoff,))
        conn.commit()
        return cur.rowcount


# ---------------------------------------------------------------------------
# DEP-004: persisted monitoring baseline (one row)
# ---------------------------------------------------------------------------

def save_baseline(snapshot: MonitoringSnapshot, saved_at: Optional[datetime] = None) -> None:
    """Upserts the single baseline row. Every MonitoringSnapshot field is
    serialized, optional ones included (aplus_candidate_key,
    nearby_high_impact_event_key), so a restored baseline diffs exactly like
    the in-memory one did."""
    saved = (saved_at or datetime.now(timezone.utc)).isoformat()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO monitoring_baseline (id, snapshot, saved_at) VALUES (1, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET snapshot = excluded.snapshot, saved_at = excluded.saved_at",
            (json.dumps(dataclasses.asdict(snapshot)), saved),
        )
        conn.commit()


def load_baseline() -> Optional[Tuple[MonitoringSnapshot, datetime]]:
    """Returns (snapshot, saved_at), or None when there is no row, or the
    row can't be rebuilt into a MonitoringSnapshot (corrupt JSON, a missing
    required field, an unparseable saved_at). An unreadable baseline is
    treated like no baseline at all: never guessed at. Unknown keys (from a
    future schema) are ignored; missing optional fields take their
    defaults."""
    with get_connection() as conn:
        row = conn.execute("SELECT snapshot, saved_at FROM monitoring_baseline WHERE id = 1").fetchone()
    if row is None:
        return None
    try:
        data = json.loads(row["snapshot"])
        known = {f.name for f in dataclasses.fields(MonitoringSnapshot)}
        snapshot = MonitoringSnapshot(**{k: v for k, v in data.items() if k in known})
        saved_at = datetime.fromisoformat(row["saved_at"])
    except (TypeError, ValueError, AttributeError):
        return None
    if saved_at.tzinfo is None:
        saved_at = saved_at.replace(tzinfo=timezone.utc)
    return snapshot, saved_at


def clear_baseline() -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM monitoring_baseline")
        conn.commit()
