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
"""
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from journal.database import get_connection
from ai.monitoring.models import AlertEvent, AlertType, Severity

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
