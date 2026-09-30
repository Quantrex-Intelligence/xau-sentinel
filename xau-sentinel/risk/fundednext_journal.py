"""Persists a FundedNext account/risk SNAPSHOT alongside each journal trade,
captured once at trade-creation time — never updated afterward, so a
historical trade's stored context can never drift as the live account
changes later.

Lives in its own table (fundednext_context), added via CREATE TABLE IF NOT
EXISTS — the frozen Stage 1 schema in journal/database.py's SCHEMA string is
never edited. Reuses journal.database.get_connection() (calling it, not
modifying it) so this data lives in the same SQLite file as everything else
rather than inventing a third storage mechanism.

One row per trade is structurally enforced (Stage 23D, VAL-030) by a UNIQUE
index on trade_id rather than a table-level UNIQUE constraint, because CREATE
TABLE IF NOT EXISTS never migrates an existing database -- see init_table().
"""
import logging
import sqlite3
from typing import Optional

from journal.database import get_connection
from risk.models import FundedNextStatus

logger = logging.getLogger(__name__)

TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS fundednext_context (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER NOT NULL REFERENCES trades(id) ON DELETE CASCADE,
    data_available INTEGER NOT NULL,
    account_type TEXT,
    phase TEXT,
    mode TEXT,
    balance REAL,
    equity REAL,
    today_pnl REAL,
    daily_loss_remaining REAL,
    daily_loss_used_pct REAL,
    max_drawdown_remaining REAL,
    max_drawdown_used_pct REAL,
    daily_loss_pct_rule REAL,
    max_loss_pct_rule REAL,
    safety_level TEXT,
    reason TEXT,
    captured_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

FIELDS = [
    "trade_id", "data_available", "account_type", "phase", "mode", "balance", "equity",
    "today_pnl", "daily_loss_remaining", "daily_loss_used_pct", "max_drawdown_remaining",
    "max_drawdown_used_pct", "daily_loss_pct_rule", "max_loss_pct_rule", "safety_level", "reason",
]


UNIQUE_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_fundednext_context_trade_id
    ON fundednext_context (trade_id);
"""


def init_table() -> None:
    """Creates the table if missing, then enforces one snapshot per trade
    (Stage 23D, VAL-030) with a UNIQUE index -- CREATE UNIQUE INDEX IF NOT
    EXISTS also applies to a database created before this stage.

    An older database may already hold duplicate rows for a trade, which
    would make the index creation fail and the app crash on startup. Those
    are removed first, keeping the EARLIEST row (lowest id) per trade_id:
    the snapshot is meant to be captured once at trade creation and never
    changed, so the first row is the genuine creation-time capture and any
    later row can only be an erroneous re-write. On a clean database the
    DELETE matches nothing. Dedupe and index commit together."""
    with get_connection() as conn:
        conn.executescript(TABLE_SCHEMA)
        removed = conn.execute(
            """DELETE FROM fundednext_context
               WHERE id NOT IN (SELECT MIN(id) FROM fundednext_context GROUP BY trade_id)"""
        ).rowcount
        if removed:
            logger.warning(
                "fundednext_context: removed %d duplicate snapshot row(s), keeping the earliest "
                "per trade, before enforcing UNIQUE(trade_id) (VAL-030)", removed,
            )
        conn.execute(UNIQUE_INDEX)
        conn.commit()


def save_snapshot(trade_id: int, status: FundedNextStatus, rules_daily_loss_pct: Optional[float],
                   rules_max_loss_pct: Optional[float],
                   conn: Optional[sqlite3.Connection] = None) -> None:
    """Writes exactly one row per trade — an INSERT, never an UPDATE. There
    is deliberately no function anywhere in this module that mutates an
    existing row, so a trade's captured context cannot be overwritten by a
    later call, however the live account changes afterward. A second call
    for the same trade raises sqlite3.IntegrityError via the UNIQUE index
    (Stage 23D, VAL-030).

    With no `conn`, opens its own connection and commits. With a caller's
    `conn` it writes into that open transaction and does NOT commit (Stage
    23D, VAL-029), so api/routes/journal.py can commit the trade and its
    snapshot atomically."""
    row = {
        "trade_id": trade_id,
        "data_available": int(status.data_available),
        "account_type": status.account_type.value,
        "phase": status.phase.value,
        "mode": status.mode,
        "balance": status.balance,
        "equity": status.equity,
        "today_pnl": status.today_pnl,
        "daily_loss_remaining": status.daily_loss_remaining,
        "daily_loss_used_pct": status.daily_loss_used_pct,
        "max_drawdown_remaining": status.max_drawdown_remaining,
        "max_drawdown_used_pct": status.max_drawdown_used_pct,
        "daily_loss_pct_rule": rules_daily_loss_pct,
        "max_loss_pct_rule": rules_max_loss_pct,
        "safety_level": status.safety_level.value,
        "reason": status.reason,
    }
    sql = f"""INSERT INTO fundednext_context ({', '.join(FIELDS)})
              VALUES ({', '.join(':' + f for f in FIELDS)})"""
    if conn is not None:
        conn.execute(sql, row)
        return
    with get_connection() as own_conn:
        own_conn.execute(sql, row)
        own_conn.commit()


def get_snapshot(trade_id: int) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM fundednext_context WHERE trade_id = ? ORDER BY id DESC LIMIT 1",
            (trade_id,),
        ).fetchone()
        return dict(row) if row else None
